# -*- coding: utf-8 -*-
"""
Created on Wed Jul 20 12:27:39 2022

@author: Manuel
"""

import matplotlib.pyplot as plt
import numpy as np
from scipy import interpolate
from scipy.ndimage import gaussian_filter


def smoothen(IdxList, factor, i):
    minFactor = factor 
    center  = len(IdxList)//2
    middleEntry = IdxList[center]
    slope = (1-minFactor)/middleEntry
    factorList_front = np.add(slope * IdxList[:center], minFactor) 
    slope_end = -slope 
    factorList_end = np.add(slope_end * IdxList[center:], 2-minFactor) 
    return np.hstack((factorList_front, factorList_end))  

def rect_mask(data, offset_x, offset_y, strength, blur=35):
    rows = data.shape[0]
    cols = data.shape[1]
    min_val = strength
    max_in = ((rows + cols) // 4)-1
    
    mask = np.full_like(data, min_val)
    slope = (1-min_val)/(max_in+1)
    # previous = min_val
    for i in range(1, max_in+1):
        fill_value = slope*(i) + min_val
        remove = 2*i
        fill_value_col = [fill_value]*(cols-remove)
        fill_value_row = [fill_value]*(rows-remove)
        mask[i, i:-i] = fill_value_row
        mask[i:-i,i] = fill_value_col
        mask[i:-i,-i-1] = fill_value_col
        mask[-i-1, i:-i] = fill_value_row
        # avg = 0
        # mask[i,i] = avg
        # mask[-i,-i] = avg
        # mask[i,-i] = avg
        # mask[-i,i] = avg
        # previous = fill_value
    
    # diag = np.diag(mask)
    # np.fill_diagonal(mask, 0)#
    # np.fill_diagonal(mask, 0)
    # for i in range(-200,200):
    #     rng = np.arange(rows-abs(i))
    #     factors = smoothen(rng, .85, i)
    #     mask[rng, rng+i] = smoothen(rng, .5, i)
    #     mask[-rng, rng+i] = smoothen(rng, .5, i)
        
    if cols % 2 != 0:
        mask[max_in+1, max_in+1] = 1
    # for j in range(0, rows):
    #     mask[j,j] = mask[j+1,j-1]
    if offset_x != 0:
        if offset_x > 0:
            mask = np.delete(mask, np.s_[-offset_x:],axis=1)
            new_cols = np.full((rows, np.abs(offset_x)), min_val)
            mask = np.column_stack((new_cols, mask))
        elif offset_x <0:
            mask = np.delete(mask, np.s_[0:-offset_x],axis=1)
            new_cols = np.full((rows, np.abs(offset_x)), min_val)
            mask = np.column_stack((mask, new_cols))
    
    if offset_y != 0:
        if offset_y > 0:
            mask = np.delete(mask, np.s_[-offset_y:],axis=0)
            new_rows = np.full((np.abs(offset_y), cols), min_val)
            mask = np.row_stack((new_rows, mask))
        elif offset_y < 0:
            mask = np.delete(mask, np.s_[0:-offset_y],axis=0)
            new_rows = np.full((np.abs(offset_y), cols), min_val)
            mask = np.row_stack((mask, new_rows))
    if blur > 0:
        mask = gaussian_filter(mask, sigma=blur)
    return mask

def triangle(length, minimum, off=0):
    minimum = np.sqrt(minimum)
    center = length//2
    factor_list = [minimum]*length
    slope = (1-minimum)/(center-off)
    front_indices = np.arange(off, center, 1)
    factor_list[off: center] = np.add(slope * front_indices , minimum) 
    slope_end = -slope 
    back_off = length-off
    back_indices = np.arange(center, back_off, 1)
    factor_list[center: back_off] = np.add(slope_end * back_indices, 2-minimum) 
    return factor_list  

def rect_mask2(data, offset_x, offset_y, strength, blur=35):
    rows = data.shape[0]
    cols = data.shape[1]
    
    mask_col = np.ones_like(data)
    mask_row = np.ones_like(data)
    for i in range(cols):
        mask_col[:,i] = triangle(rows, strength, 0)
        
    for i in range(rows):
        mask_row[i, :] = triangle(cols, strength, 0)
    mask = mask_row*mask_col
    if offset_x != 0:
        if offset_x > 0:
            mask = np.delete(mask, np.s_[-offset_x:],axis=1)
            # new_cols = np.full((rows, np.abs(offset_x)), min_val)
            # mask = np.column_stack((new_cols, mask))
        elif offset_x <0:
            mask = np.delete(mask, np.s_[0:-offset_x],axis=1)
            # new_cols = np.full((rows, np.abs(offset_x)), min_val)
            # mask = np.column_stack((mask, new_cols))
    
    if offset_y != 0:
        if offset_y > 0:
            mask = np.delete(mask, np.s_[-offset_y:],axis=0)
            # new_rows = np.full((np.abs(offset_y), cols), min_val)
            # mask = np.row_stack((new_rows, mask))
        elif offset_y < 0:
            mask = np.delete(mask, np.s_[0:-offset_y],axis=0)
            # new_rows = np.full((np.abs(offset_y), cols), min_val)
            # mask = np.row_stack((mask, new_rows))
    x = np.linspace(0, 1, mask.shape[0])
    y = np.linspace(0, 1, mask.shape[1])
    f = interpolate.interp2d(y, x, mask, kind='cubic')
      
    x2 = np.linspace(0, 1, cols)
    y2 = np.linspace(0, 1, rows)
    _mask = f(y2, x2)
    if blur > 0:
        _mask = gaussian_filter(_mask, sigma=blur)
    return _mask
    
def inverse(data, xc, yc, strength, gamma=1):
    xc += data.shape[1]//2
    yc += data.shape[0]//2
    print(xc, yc)
    mask_strength = strength
    print('Preparing circular mask with strength %.1f'%strength)
    x = np.linspace(0,data.shape[1], data.shape[1])
    y = np.linspace(0,data.shape[0], data.shape[0])
    xx, yy = np.meshgrid(x,y)
    r_squared = (xx-xc)**2+(yy-yc)**2
    max_offset = np.max(r_squared)
    print('Preparing circular mask with strength %.1f'%strength)
    exponent = -np.log(mask_strength)/(np.log(max_offset))
    # such that the minimal scale factor of the mask equals the mask strength
    f = 1/(gamma*(r_squared)**exponent)
    f[f>1] = 1
    return  f # 1/r^2 function


def gaussian(xy, xc, yc, a, b, A): # xy = x,y is is important for fitting (function may only depend on one parameter)
            x,y = xy
            return A*(np.exp(-a*((x-xc)**2) - b*((y-yc)**2))).ravel()     # product of x- and y-gaussian exp(-a(x-x0)**2) * exp(-b(y-y0)**2)
        
def lorentzian(data, xc, yc, strength, max_val=1):
    xc += data.shape[1]//2
    yc += data.shape[0]//2
    x = np.linspace(0,data.shape[1], data.shape[1])
    y = np.linspace(0,data.shape[0], data.shape[0])
    xx, yy = np.meshgrid(x,y)
    strength*=1000
    lorentz =  (strength/((xx-xc)**2+ (yy-yc)**2+ strength**2))
    lorentz = lorentz/np.amax(lorentz) * max_val
    return lorentz


def linear(xy, xc=220, yc=240, Imax=65000, m=-3):
    x,y = xy
    outer = np.multiply(np.sqrt((x-xc)**2+(y-yc)**2), m).ravel()
    return np.add(Imax, outer) # polar coor: I(r) = r*m + I_max

def quadratic(xy, xc=220, yc=240, Imax=65000, m=-3):
    x,y = xy
    outer = np.multiply((x-xc)**2+(y-yc)**2, m).ravel()
    return np.add(Imax, outer) # polar coor: I(r) = r*m + I_max

if __name__ == '__main__':
    dummy_data = np.ones((513,513))
    mask = rect_mask(dummy_data, 0, 0, .2)
    diag = np.diag(mask)
    im = plt.imshow(mask, vmin=0, vmax=1)
    plt.gcf().colorbar(im)
    plt.title('Rectangular mask demo')
    plt.show()
    
    mask = rect_mask(dummy_data, 0, 0, .2, blur=0)
    im = plt.imshow(mask, vmin=0, vmax=1)
    plt.gcf().colorbar(im)
    plt.title('Rectangular mask w/o Gauss filter')
    plt.show()
    
    
    circ_mask = inverse(dummy_data, 0, 0, .2, gamma=4)
    circ_mask = gaussian_filter(circ_mask, sigma=10)
    im2 = plt.imshow(circ_mask)
    plt.gcf().colorbar(im2)
    plt.title('Circular mask demo')
    plt.show()
    # Here the issue becomes obvious --> artifacts


    im = plt.imshow(rect_mask2(dummy_data, 170,140, .5))    
    plt.gcf().colorbar(im)
    plt.title('Customized rectangular mask demo')
    plt.show()
    
    gamma=1
    im = plt.imshow(lorentzian(dummy_data, 0,0, gamma, max_val=1))    
    plt.gcf().colorbar(im)
    plt.title('Lorentzian $\gamma = %.1f$'%gamma)
    plt.show()
    
    