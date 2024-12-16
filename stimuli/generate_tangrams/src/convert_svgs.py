from os import listdir
import os
from os.path import isfile, join
import glob
from cairosvg import svg2png
from pathlib import Path

from config import RAW_TANGRAMS_SVGS, PROCESSED_TANGRAMS_SVGS, PROCESSED_PNGS

tangram_files = [f for f in listdir(RAW_TANGRAMS_SVGS) if isfile(join(RAW_TANGRAMS_SVGS, f))]

for file in tangram_files:
  if file.startswith('page'):

    f = open(join(RAW_TANGRAMS_SVGS, file),'r').read().replace("\n"," ")
    f = f.replace('fill="lightgray"','fill="black"')
    f = f.replace('stroke="white" strokewidth="1"','stroke="black" strokewidth="2"')
    # f = f.replace('stroke="white" strokewidth="1"','stroke="black" strokewidth="2"')
    with open(PROCESSED_TANGRAMS_SVGS+file, 'w') as new_f:
      new_f.write(f)

files = glob.glob(PROCESSED_TANGRAMS_SVGS + '/**/*.svg', recursive=True)

new_files = [os.path.splitext(text)[0]+'.png' for text in files]

for i in range(0, len(files)):
    svg2png(url=files[i], write_to=new_files[i]) # fix this so it goes to PROCESSED_PNGS