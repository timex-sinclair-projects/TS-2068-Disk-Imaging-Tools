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

# Adapted from: http://www.andrew-seaford.co.uk/generate-safe-filenames-using-python/
## Make a file name that only contains safe charaters  
# @param inputFilename A filename containing illegal characters  
# @return A filename containing only safe characters  
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
        sides = block[20]
        tracks = block[21]
        divideblocks = False
        file_stats = os.stat(fileName)
        print("Sides: ",sides)
        print("Tracks: ",tracks)
        print("File size: ",file_stats.st_size)
        if file_stats.st_size < 250000 and sides == 1:
            #print ("Small image size")
            divideblocks = True
        elif sides == 1 and file_stats.st_size > 400000:
            logBadFile(fileName,"Single sided imaged as double sided.")
            sys.exit("Extraction ended. Single sided disk with too many bytes.")
        total_blocks = sides*tracks
        print("Divide blocks:",divideblocks)
        i = 188
        fileDirectory = []
        while block[i] != 250: # 250 is end of directory code
            #currChar = block[i]
            if block[i] == 255: # Start of directory Name Cell
                i += 1 # move to the first character of the file name or the not in use marker
                if block[i] != 254:  #this cell is not in use
                    tempFileName = ''
                    while block[i] != 253:
                        tempFileName += chr(block[i])
                        i += 1
                else:  # seek to the end of the directory or next cell
                    i += 1
                    while block[i] != 250 or block[i] !=255:
                        if block[i] == 250:
                            i -= 1
                            break
                        elif block[i] == 255:
                            i -= 1
                            break
                        i += 1

            if block[i] == 253: # beginning of block list for this file
                i += 1
                blocklist = []
                if block[i] != 249:
                    while block[i] != 249:
                        if divideblocks:
                            blocklist.append(block[i]//2)
                        else:
                            blocklist.append(block[i])
                        i += 1

                    # create a dict from the tempFileName and its block list
                    thisdict = {
                        "filename": tempFileName,
                        "blocks": blocklist,
                        "type": fileType(tempFileName)
                    }
                    fileDirectory.append(thisdict)
            #if block[i] == 254: # Follows 255 if cell is not in use
            #    i += 1
            #    continue
            #print(i,block[i])
            i += 1
    #print(fileDirectory)
    fd.close()
    return fileDirectory

def fileType(fileName):
    #print(fileName)
    if "." in str(fileName):
        fileDetails = str(fileName).split(".")
        ft = fileDetails[1]
        if ft[0] == "B":            # BASIC program
            return b'\x00'
        elif ft[0] == "C":          # CODE
            return b'\x03'
        if ft[0] == "A":            # Array variable
            if ft[1] == "$":
                return b'\x02'       # string array
            else:
                return b'\x01'      # numeric array
    else:
        return b'\x00'


def readFile(fileName,fileDict):
    with open(fileName,'r+b',0) as fd:
        fileContent = bytearray()
        fileData = {}
        #print(fileDict["filename"])
        firstBlock=fileDict["blocks"][0]
        #print(firstBlock)
        for y in fileDict["blocks"]:
            seekVal = y * 5120
            fd.seek(seekVal)
            fileBlock = fd.read(5120)
            if fileBlock[0] != 255:
                print(fileBlock[0])
                logBadFile(fileName,"First byte of block is not FF.")
                sys.exit("Extraction ended. First byte of block is not FF.")
            if y == firstBlock:
                fileData["fileNameBytes"] = fileBlock[2:11] + b'\x20' #Larken filenames are 9 bytes, add a space to pad it out.
                if fileData["fileNameBytes"].decode().rstrip() != fileDict["filename"].rstrip():
                    logBadFile(fileName,"File names do not match.")
                    print(fileData["fileNameBytes"].decode().rstrip())
                    sys.exit("Extraction ended. File is probably corrupt.")
                fileData["fileStartAddr"] = int.from_bytes(fileBlock[12:14], "little")
                fileData["fileAutoStartLine"] = int.from_bytes(fileBlock[17:19],"little")
                fileData["varProgOffset"] = int.from_bytes(fileBlock[20:22],"little")
                fileData["fileLength"] = int.from_bytes(fileBlock[22:24],"little")
                fileData["type"] = fileType(fileData["fileNameBytes"])
            dataSize = int.from_bytes(fileBlock[14:16],"little")
            #print(" Start address of file: ",fileStartAddr)
            #print(" Length of data on block: ",dataSize)
            #print("CRC: ")
            #print(" Auto start line number: ",fileAutoStartLine)
            #print(" Variable - prog (offset for BASIC): ",varProgOffset)
            #print(" Total length of file: ",fileLength)
            fileContent.extend(fileBlock[24:dataSize+24])
        fileData["fileContent"] = fileContent
        fd.close()
        return fileData

def logBadFile(filename,mesg):
    with open("badfiles","a") as bf:
        bf.write(filename + "," + mesg + chr(13))
        bf.close()

def writeTapFile(filePath,fileData):
    filename = fileData["fileNameBytes"].decode('UTF-8').rstrip()
    #print(filename)
    fileHeader = b'\x13\x00'
    thisFileH = b'\x00' + fileData["type"] + fileData["fileNameBytes"] + len(fileData["fileContent"]).to_bytes(2,"little") + fileData["fileAutoStartLine"].to_bytes(2,"little") + fileData["varProgOffset"].to_bytes(2,"little")
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
            safefileName = filePath + "\\" + safefileName
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
        print(f'{fitem["filename"]:12}  {fitem["blocks"]} {fitem["type"]}')
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
            fileDetails = firstSplit[0].rsplit("\\",1)
            path = fileDetails[1]
            #print("Create directory:",dirname)
            try:
                os.mkdir(path)
                print("Folder %s created!" % path)
            except FileExistsError:
                print("Folder %s already exists" % path)

        if args.specific:
            for fitem in cat:
                print(fitem)
                if fitem["filename"].rstrip() == args.specific:
                    print(fitem)
                    print(readFile(args.imgfile,fitem))
            exit(0)
        for fitem in cat:
            print("Extracting: ",fitem)
            thisFileContent = readFile(args.imgfile,fitem)
            #print(thisFileContent["fileNameBytes"])
            writeTapFile(path,thisFileContent)
    else:
        print("Empty catalog.")
        