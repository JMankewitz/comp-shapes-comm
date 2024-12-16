from config import PROCESSED_TANGRAMS_WHITE, PROCESSED_TANGRAMS_TRANS, PROCESSED_PNGS, MAPPING_FILE
import numpy as np
import glob
from PIL import Image
import cv2

# TODO: Could be batched w/ a function

shape_pngs = sorted(glob.glob(PROCESSED_PNGS + '/*.png', recursive=True))
import csv

with open(MAPPING_FILE, 'w') as f:
    writer = csv.writer(f)
    writer.writerows(zip(shape_pngs, list(range(len(shape_pngs)))))

    # Construct these on the gpu...
imgs = [ Image.open(i) for i in  shape_pngs ]

for i in range(len(imgs)):
    print(shape_pngs[i])
    for j in range(len(imgs)):
        file_trans = PROCESSED_TANGRAMS_TRANS + str(i) + "_" + str(j) + '.png'
        file_white = PROCESSED_TANGRAMS_WHITE + str(i) + "_" + str(j) + '.png'
        images = [imgs[i], imgs[j].rotate(180)]
        #min_shape = sorted( [(np.sum(i.size), i.size ) for i in images])[0][1]
        imgs_comb = np.vstack([i.resize((256, int(256/2))) for i in images])
        imgs_comb = Image.fromarray( imgs_comb)
        imgs_comb.save( file_trans )
        img = cv2.imread(file_trans, cv2.IMREAD_UNCHANGED)
        if img.shape[2] == 4:     # we have an alpha channel
            a1 = ~img[:,:,3]        # extract and invert that alpha
            img = cv2.add(cv2.merge([a1,a1,a1,a1]), img)   # add up values (with clipping)
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)
        cv2.imwrite(file_white, img)