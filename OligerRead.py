import argparse
from pickle import FALSE, TRUE
parser = argparse.ArgumentParser()
parser.add_argument("-f","--imgfile",type=str,help="You must provide an IMG filename for input")
parser.add_argument("-c","--cat",help="Catalog of disk image contents", action='store_true')
parser.add_argument("-s","--specific",type=str,help="Optional: name of a specific program to extract")
parser.add_argument("-d","--directory",type=str,help="Optional: name of directory files are in")
parser.add_argument("-i","--id",help="Identify disk type",action="store_true")
parser.add_argument("-o","--outdir",help="Output files to directory based on name", action='store_true')
args = parser.parse_args()

import os
import sys
import time

from os import listdir
from os.path import isfile, join

import string


# Oliger directory starts at 600h
# Dir Format
# Byte 0: Tracks
# Byte 1: Sides
# Byte 2: Total cylinders - 1 (for directory)
# Byte 3: unknown
# Byte 4: Available cylinders
# Byte 5: unknown
# Byte 6: Next free cyl * 2 (rotate left)
# Byte 7: FF if next free cyl is odd, add one to value in byte 6
# Byte 8: unknown
# Byte 9: unknown
# Bytes 10-16: E5 so far
# Bytes 17-31: Disk name

# Directory entry, starts at 620h
# each entry is 20 bytes
# Bytes 0-9: File name
# Byte 10: File format (0 = Basic, 1 = Num Array, 2 = Char Array, 3 = CODE)
# Byte 11: File size LSB
# Byte 12: File size MSB
# Byte 13: Starting line # LSB
# Byte 14: Starting line # MSB
# Byte 15: Param 2 LSB
# Byte 16: Param 2 MSB
# Byte 17: Next free cyl * 2 (rotate left)
# Byte 18: FF if next free cyl is odd, add one to value in byte 17; 1 if byte 17 is 0
# Byte 19: Cylinders used

# Directory ends with 80h after last directory entry

# Adapted from: http://www.andrew-seaford.co.uk/generate-safe-filenames-using-python/
## Make a file name that only contains safe charaters  
# @param inputFilename A filename containing illegal characters  
# @return A filename containing only safe characters  

fileTypes = ["BASIC","Numeric array","String array","CODE"]

def makeSafeFilename(inputFilename):
    # Set here the valid chars
    safechars = string.ascii_letters + string.digits + "~ -_."
    try:
        f = filter(lambda c: c in safechars, inputFilename)
        s="".join(f)
        return s
    except:
        return ""
    pass  

def cylinderNumber(bytes):
    result = bytes[0]*2
    if bytes[1] != 0:
        result = result + 1
    return result

#function to return files in a directory
def fileInDirectory(my_dir: str):
    onlyfiles = [f for f in listdir(my_dir) if isfile(join(my_dir, f))]
    return(onlyfiles)

def doThingsWithNewFiles(fileList):
    print("New files: ",fileList)
    for thisFile in fileList:
        # process the file
        print("Processing: ",thisFile)
        # get a directory of imgfile
        cat = catfiles(thisFile)
        for fitem in cat:
            print(readFile(thisFile,fitem))

# fileName is tapFile

def is_even(num):
    return num % 2 == 0

def bytes_to_int(toIntVal):
    result = 0
    for b in toIntVal:
        result = result * 256 + int(b)
    return result

def crc(crcVal):
    result = 0
    for b in crcVal:
        #print(result,b)
        result = result ^ b
    return result.to_bytes(1,"little")

def catfiles(fileName):
    with open(fileName,'r+b',0) as fd:
        block = fd.read(5120)
        sides = block[1537]
        tracks = block[1536]
        diskname = block[1552:1568].decode()
        total_cylinders = block[1537]
        divideblocks = False
        file_stats = os.stat(fileName)
        print("Disk: ",diskname)
        print("Sides: ",sides)
        print("Tracks: ",tracks)
        print("File size: ",file_stats.st_size)
        if file_stats.st_size < 250000 and sides == 1:
            #print ("Small image size")
            divideblocks = True
        elif sides == 1 and file_stats.st_size > 400000:
            logBadFile(fileName,"Single sided imaged as double sided.")
            sys.exit("Extraction ended. Single sided disk with too many bytes.")
        #print("Divide blocks:",divideblocks)
        fileStart = 1568
        entrySize = 20
        fileDirectory={}
        fileDirectoryEntry = block[fileStart:fileStart+entrySize]
        while fileDirectoryEntry[0] != 128: # 128 is end of directory
            thisEntry={}
            thisEntry["filename"]=fileDirectoryEntry[0:10].decode()
            thisEntry["filetype"]=fileDirectoryEntry[10]
            thisEntry["filesize"]=int.from_bytes(fileDirectoryEntry[11:13], "little")
            thisEntry["staline"]=int.from_bytes(fileDirectoryEntry[13:15], "little")
            thisEntry["param2"]=int.from_bytes(fileDirectoryEntry[15:17],"little")
            thisEntry["cylinder"]=cylinderNumber(fileDirectoryEntry[17:19])
            thisEntry["cylused"]=fileDirectoryEntry[19]
            fileStart += entrySize
            fileDirectory[fileStart]=thisEntry
            fileDirectoryEntry = block[fileStart:fileStart+entrySize]
    fd.close()
    return fileDirectory

def fileType(typeByte):
    #print(fileName)

    return fileTypes[typeByte]



def readFile(fileName,fileDict):
    with open(fileName,'r+b',0) as fd:
        fileContent = bytearray()
        fileData = fileDict
        print(fileDict)
        startCyl = fileDict["cylinder"]
        cylsUsed = fileDict["cylused"]
        currCyl = 0
        while currCyl < cylsUsed:
            seekVal = (startCyl + currCyl) * 5120
            fd.seek(seekVal)
            fileBlock = fd.read(5120)
            #print(fileBlock)
            fileContent.extend(fileBlock)
            currCyl += 1
        fileData["fileContent"] = fileContent[:fileDict["filesize"]]
        fd.close()
        return fileData

def logBadFile(filename,mesg):
    with open("badfiles","a") as bf:
        bf.write(filename + "," + mesg + chr(13))
        bf.close()

def writeTapFile(filePath,fileData):
    #print(fileData)
    filename = fileData["filename"].rstrip()
    #print(filename)
    fileHeader = b'\x13\x00'
    thisFileH = b'\x00' + fileData["filetype"].to_bytes(1,"little") + fileData["filename"].encode('utf-8') + len(fileData["fileContent"]).to_bytes(2,"little") + fileData["staline"].to_bytes(2,"little") + fileData["param2"].to_bytes(2,"little")
    #print ("Header length:",len(thisFileH))
    crcVal =  crc(thisFileH) # get the crcVal for the header
    thisFileH += crcVal
    fileCRCVal = crc(b'\xff' + fileData["fileContent"]) #get the crcVal for the filecontent
    dataBlock = b'\xff' + fileData["fileContent"] + fileCRCVal
    #print(len(dataBlock),len(bytes(dataBlock)), len(dataBlock).to_bytes(2,"little"))
    dataBlockLen = len(dataBlock).to_bytes(2,"little")
    fout = fileHeader + thisFileH + dataBlockLen + dataBlock
    #print(thisFileH)
    #print(fileHeader)
    safefileName = makeSafeFilename(filename)
    if len(safefileName):
        if len(filePath):
            safefileName = filePath + "/" + safefileName
        fileOutput = open(safefileName + ".tap","wb")
        fileOutput.write(bytes(fout))
        fileOutput.close()
    else:
        print("Unsafe filename: ",filename)
        

if args.cat:
    # display a catalog of the img file
    print("Catalog")
    print("---------------------------------------------------")
    cat = catfiles(args.imgfile)
    #print(cat)
    for fitem in cat:
        # print(cat[fitem])
        print(f'{cat[fitem]["filename"]:12} {cat[fitem]["filesize"]} {cat[fitem]["cylinder"]} {cat[fitem]["filetype"]}')
        #for fname,fblocks,ftype in fitem.items():
        #    print(fname,fblocks,ftype)
    exit(0)


if args.imgfile:
    # process the file
    print("Processing: ",args.imgfile)
    # get a directory of imgfile
    cat = catfiles(args.imgfile)
    if len(cat):
        #print(cat)
        path = ''
        if args.outdir:
            # create a directory based on the filename
            firstSplit = str(args.imgfile).rsplit(".",1)
            #print(firstSplit[0])
            #fileDetails = firstSplit[0].rsplit("\\",1)
            path = firstSplit[0]
            #print("Create directory:",dirname)
            try:
                os.mkdir(path)
                print("Folder %s created!" % path)
            except FileExistsError:
                print("Folder %s already exists" % path)

        if args.specific:
            for fitem in cat:
                print(fitem)
                if cat[fitem]["filename"].rstrip() == args.specific:
                    print(cat[fitem])
                    print(readFile(args.imgfile,cat[fitem]))
            exit(0)
        for fitem in cat:
            print("Extracting: ",cat[fitem]["filename"])
            thisFileContent = readFile(args.imgfile,cat[fitem])
            #print(thisFileContent["fileNameBytes"])
            writeTapFile(path,thisFileContent)
    else:
        print("Empty catalog.")
        