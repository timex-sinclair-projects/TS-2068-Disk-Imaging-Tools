import argparse
from pickle import FALSE, TRUE
parser = argparse.ArgumentParser()
parser.add_argument("infile",type=str,help="File you want to read.")
#parser.add_argument("outfile",type=str,help="Where to save your output")
parser.add_argument("-s","--strip",help="Optional: remove excess white space.",action="store_true")
parser.add_argument("-f","--format",help="Input format. T for Tasword (default), M for MScript.",action="store_true")
args = parser.parse_args()

#partition('sep', 1)[0]

import os
import sys
import time
import re
import string

from os import listdir
from os.path import isfile, join

# Adapted from: http://www.andrew-seaford.co.uk/generate-safe-filenames-using-python/
## Make a file name that only contains safe characters  
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

if args.infile:
    # process the file
    print("Processing: ",args.infile)
    outfile = args.infile.partition('.')[0] + '.txt'
    outfile = makeSafeFilename(outfile)

    with open(args.infile,'rb') as fd:
        fileContent = fd.read().decode ('ascii', 'ignore')
        fileContent = fileContent[24:]
        #fileContent = fileContent.decode()
        # print(fileContent)
        fileContent = re.sub('\r','\n',fileContent)
        fileContent = re.sub(' {32}','\n',fileContent)
        fileContent = re.sub(r" +"," ",fileContent)
        fileContent = re.sub(r"\n ","\n",fileContent)
        fileContent = re.sub(r'[\x00,\x7f-\xff]','', fileContent)
        fd.close()
    with open(outfile,"w") as fd:
        fd.write(fileContent)
        fd.close()
    print("Converted: ",outfile)