# -*- coding: utf-8 -*-
"""
Created on Wed Aug 24 11:02:00 2022

@author: Manuel
"""

import numpy as np
import scipy.signal
import tifffile as tiff
import matplotlib.pyplot as plt
import stitch_functions as stitching
import time
from tkinter.messagebox import showerror

import logging

logger = logging.getLogger(__name__)

def lin_weights(overlap, max_weight=1): # first avg = top image, last avg = bottom_image
    m = ((.5-max_weight)/(overlap/2+1)) # slope triangle y = mx+b
    weight_list = []
    half_overlap = overlap//2
    for i in range(0, half_overlap):
            l_weight = m*i + max_weight
            r_weight = 1 - l_weight
            weight_list.append([l_weight, r_weight])
    reversed_weights = list(reversed([li[::-1] for li in weight_list])) # flip the lists in the list
    if overlap % 2 != 0:
        weight_list.append([.5 ,.5])
    weight_list = weight_list + reversed_weights
    return weight_list

def cross_image(img1, img2, channels=None):
    # remove nans as results become much worse with nans
    nan1 = np.isnan(img1)
    nan2 = np.isnan(img2)
    im1 = img1.copy()
    im2 = img2.copy()
    
    im1[nan1] = 0
    im2[nan2] = 0
    # get rid of the channels by performing a grayscale transform
    # the type cast into 'float' is to avoid overflows
    if channels is None:
        # print('Correlating all channels')
        im1_sum = np.sum(im1.astype('float'), axis=2)
        im2_sum = np.sum(im2.astype('float'), axis=2)
    else:
        # print('Correlating channels %s'%channels)
        im1_sum = np.sum(im1[:,:,channels].astype('float'), axis=2)
        im2_sum = np.sum(im2[:,:,channels].astype('float'), axis=2)
     # get rid of the averages, otherwise the results are not good
    im1_sum -= np.mean(im1_sum)
    im2_sum -= np.mean(im2_sum)
 
    # calculate the correlation image; note the flipping of onw of the images
    return scipy.signal.fftconvolve(im1_sum, im2_sum[::-1,::-1], mode='same')  # im2 rotated by 180° (mirrors both horizontally and vertically)

    
def max_correlation(im1, im2, channels = None, _plot=False):
    """
    Function, which returns the displacement of the maximum correlation 
    from the center of two input images (which need to overlap partly)

    Parameters
    ----------
    im1 : array
        DESCRIPTION.
    im2 : array
        DESCRIPTION.
    channels : list or int, optional
        If channels is passed to the function, only the channels specified will
        be convoluted. The default is None --> all channels are convoluted.
    _plot : boolean, optional
        DESCRIPTION. The default is False.

    Returns
    -------
    offset : TYPE
        DESCRIPTION.

    """
    corr_img = cross_image(im1, im2, channels)
    if _plot:
        plt.imshow(corr_img)
        plt.show()
    center = np.divide(corr_img.shape, 2)
    max_corr = np.unravel_index(np.argmax(corr_img), corr_img.shape)   # brightest spot
    offset = np.subtract(center, max_corr)
    """
    if _plot:
        max_val = corr_img[max_corr]
        corr_img = np.divide(corr_img, max_val)  # normalization
        new_fig, ax = plt.subplots(1,1)
        ax.imshow(corr_img)
        further_possibilities = np.where(corr_img > .7)
        print(further_possibilities)
        plt.imshow(corr_img)
        plt.title('Offset: %s; Pixels: %s, Ratio: %f'%(offset, np.shape(further_possibilities)[-1], corr_img[int(center[0]), int(center[1])]))
        plt.scatter(max_corr[1], max_corr[0], marker='x', c='r', linewidths=1)
        plt.scatter(further_possibilities[1], further_possibilities[0], marker='x', c='r', linewidths=1)
        plt.show()
        print('-'*20)
    """
    # translate_offset_to_text(offset)
    return offset 

def row_correlation(data, lookup_x, lookup_y, overlap_row, mode,
                    sigma_interval = 1, channel_list = None):
    """
    

    Parameters
    ----------
    data : dict
        The dict returned by stitch_load.
    lookup_x : list
        returned by stitch_load.
    lookup_y : list
        returned by stitch_load.
    overlap_row : int
        Pixel overlap of adjacent images. Must not be exactly known. The region used for averaging.
    mode : str, optional
        {'mean', 'sigma', 'sigma mean'}
        'sigma': discards outliers based on the sigma interval.
        'mean': averages over all correlations to get a single offset value.
        if both are selected, first outliers are removed, then the mean is calculated.
    sigma_interval : int, optional
        confidence interval used to accept offset values.
    Returns
    -------
    Array with correlations.

    """
    corr_list = []
    for i, xpos in enumerate(lookup_x):
        for j, ypos in enumerate(lookup_y[:-1]):
            overlap_top = data[xpos][ypos]['img'][-overlap_row:,:,:]
            overlap_bot = data[xpos][lookup_y[j+1]]['img'][:overlap_row,:,:]
            offset = max_correlation(overlap_top, overlap_bot, channels=channel_list, _plot=False)
            corr_list.append(offset)
    modes = set(mode.lower().split())   # to allow multiple modes, converts "SIGMA mEan" to {'sigma', 'mean'}
    print(modes)
    if 'sigma' in modes:
        modes.remove('sigma')
        corr_list = remove_outliers(corr_list, sigma_interval)
        corr_list = np.nan_to_num(corr_list, copy=False)
    if 'mean' in modes:
        # average over all correlations, each image is offset by the same value
        a = np.array(corr_list)
        corr_list = np.mean(a, axis=0)
        corr_list = np.array([corr_list] * len(a))
    print(corr_list)
    return corr_list
        
def adjust_y(im_top, im_bot, offset, overlap):
    """
    Function, which returns the top and bottom data (incl. overlap) with their 
    correct relative position by adding dummy data 
    
    Parameters
    ----------
    im_top : array
        DESCRIPTION.
    im_bot : array
        must have the same dimension along axis 1 in case of type_ = 'row' 
        resp. axis 0 in case of type_ = 'column'.
    offset : list 
        DESCRIPTION.
    overlap : int
        DESCRIPTION.
    type_ : TYPE, optional
        DESCRIPTION. The default is 'row'.

    Returns
    -------
    im_top : TYPE
        DESCRIPTION.
    im_bot : TYPE
        DESCRIPTION.
    overlap_im_top : TYPE
        DESCRIPTION.
    overlap_im_bot : TYPE
        DESCRIPTION.

    """
    # im_top is top
    # im_bot is bottom image
    # the next image is always shorter since there was no dummy appended
    im_bot = extend(im_bot, im_top.shape[1])
    
    
    overlap_im_top = im_top[-overlap:,:,:]   
    overlap_im_bot = im_bot[:overlap,:,:]
    im_top = im_top[:-overlap,:,:] 
    im_bot = im_bot[overlap:,:,:]
    print('overlap input:\n', overlap_im_top.shape, overlap_im_bot.shape)
    
    # slicing is slightly faster than take_indices
    int_offset_row = int(offset[0])
    if int_offset_row != 0:
        if int_offset_row > 0:   
            print('Bottom image is shifted downwards by %i pixels'
                  %(int_offset_row))
            # indices_im_top = np.arange(-int_offset_row, 0)
            # indices_im_bot = np.arange(int_offset_row)
            top_slice = np.s_[-int_offset_row:]
            bot_slice = np.s_[:int_offset_row]
            # in this case no rows must be added to the im_top and im_bot data
            # only remove those from the overlap 
        else:
            print('Bottom image is shifted upwards by %i pixels'
                  %(int_offset_row))
            int_offset_row = abs(int_offset_row)
            # indices_im_bot = np.arange(-int_offset_row, 0)
            # indices_im_top = np.arange(int_offset_row)
            
            bot_slice = np.s_[-int_offset_row:]
            top_slice = np.s_[:int_offset_row]
            
            # most outer end of overlaps are removed, we have to attach them to the data again
            print('Adding row overhang of overlaps to the intial data')
            print(overlap_im_top.shape, overlap_im_bot.shape)
            overhang_im_top = overlap_im_top[top_slice,:,:]
            im_top = np.concatenate((im_top, overhang_im_top), axis=0)
            overhang_im_bot = overlap_im_bot[bot_slice,:,:]
            print(overhang_im_top.shape, overhang_im_bot.shape)
            im_bot = np.concatenate((overhang_im_bot, im_bot), axis=0)
        # delete the overhang in overlaps
        overlap_im_top = np.delete(overlap_im_top, top_slice, axis=0)
        overlap_im_bot = np.delete(overlap_im_bot, bot_slice, axis=0)
        print('overlap output:\n', overlap_im_top.shape, overlap_im_bot.shape)
    return im_top, im_bot, overlap_im_top, overlap_im_bot


def adjust_x(im_left, im_right, offset, overlap, _plot=False):
    # im1 is left image
    # im2 is bottom or right image
    # the next image is always shorter since there was no dummy appended        
    overlap_im_left = im_left[:,-overlap:,:]   
    overlap_im_right = im_right[:, :overlap,:]
    im_left = im_left[:, :-overlap,:] 
    im_right = im_right[:, overlap:,:]
    print('overlap input:\n', overlap_im_left.shape, overlap_im_right.shape)
    print('im input:\n', im_left.shape, im_right.shape)
    
    
    int_offset_col = int(offset[1])
    if int_offset_col != 0:
        # here it is the opposite case as in adjust y since the correlation
        # function treats the column images as row images
        # thus signs are reversed
        
        if int_offset_col > 0:   
            print('Left image is shifted towards the left by %i pixels'
                  %(int_offset_col))
            right_slice = np.s_[-int_offset_col:]
            left_slice =  np.s_[:int_offset_col]
            # most outer end of overlaps are removed, we have to attach them to the data again
            print('Adding row overhang of overlaps to the intial data')
            overhang_im_left = overlap_im_left[:, left_slice,:]
            im_left = np.concatenate((im_left, overhang_im_left), axis=1)
            overhang_im_right = overlap_im_right[:,right_slice,:]
            print(overhang_im_left.shape, overhang_im_right.shape)
            im_right = np.concatenate((overhang_im_right, im_right), axis=1)
        else:
            int_offset_col = abs(int_offset_col)
            print('Left image is shifted towards the right by %i pixels'
                  %(int_offset_col))
            # print('THIS IS UNREALISTIC'*100)
            # correct x offset
            right_slice = np.s_[:int_offset_col]
            left_slice = np.s_[-int_offset_col:]
            # in this case no rows must be added to the im_left and im_right data
            # only remove those from the overlap 
        # delete the overhang in overlaps
        overlap_im_left = np.delete(overlap_im_left, left_slice, axis=1)
        overlap_im_right = np.delete(overlap_im_right, right_slice, axis=1)
        if _plot:
            plt.imshow(np.concatenate((im_left, overlap_im_left, overlap_im_right, im_right), axis=1)[:,:,ch], vmax=vmax_var)
            plt.title('Corrected x-offset')
            plt.show()
        print('overlap output:\n', overlap_im_left.shape, overlap_im_right.shape)
    return im_left, im_right, overlap_im_left, overlap_im_right


def correct_y_offset(stitch_im, bot_im, offset, overlap, dummy, _plot=False):
    print(dummy)
    print(offset)
    x_max = bot_im.shape[1] # initial number of colums (e.g. 512)
    x_max_data = x_max + dummy[0]   # max index where no nans
    bot_im = add_cols(bot_im, dummy)    # matches the image shape such that the calculated offset is correct
                                        # by adding the same dummy again
    # offset[0] is y-direction and offset[1] x-direction
    # offset[0] < 0: top image is translated downwards by |offset[0]| pixels
    # offset[0] > 0: top image is translated upwards by offset[0] pixels
    # offset[1] < 0: top image is translated to the right by  |offset[1]| pixels
    # offset[1] > 0: top image is translated to the left by offset[1] pixels
    
    # row offset 
    top, bot, overlap_top, overlap_bot = adjust_y(stitch_im, bot_im, offset, overlap)
    int_offset_col = int(offset[1])
    xstart = dummy[0]
    x_min = abs(int_offset_col) # min x index of the image w/o dummy 
    x_l = dummy[0]
    top_overlap = top.shape[0]+overlap_top.shape[0]
    print('-'*5)
    if int_offset_col != 0:
        dummy_bot = np.full((bot.shape[0], abs(int_offset_col), bot.shape[2]), np.NaN)
        dummy_top = np.full((top.shape[0], abs(int_offset_col), top.shape[2]), np.NaN)
        dummy_overlap = np.full((overlap_top.shape[0], abs(int_offset_col), overlap_top.shape[2]), np.NaN)
        if int_offset_col > 0:            
            # add dummy signal to top left and bottom right
            print('Bottom image is shifted towards the right by %i pixels'
                  %(int_offset_col))
            # top_slice = np.s_[-int_offset_col:]
            # bot_slice = np.s_[:int_offset_col]
            print('Extending bottom right and top left to match shape after correlation')
            top_extension = (dummy_top, top)
            bot_extension = (bot, dummy_bot)
            o_top_extension = (dummy_overlap, overlap_top)
            o_bot_extension = (overlap_bot, dummy_overlap)
            # parts of stitch center not averaged, will be appended later
            x_l += int_offset_col
            stitch_left = overlap_bot[:,dummy[0]:x_l,:]
            stitch_right = overlap_top[:,-int_offset_col -dummy[1]: overlap_top.shape[1]-dummy[1],:]
            print(stitch_right.shape[1])
            print('Bottom right is expanded with dummy signal')
            new_overhang = [0, int_offset_col] # save that dummy was added to bottom right for next correlation
            connections = {'left': [top.shape[0]],
                           'right':[top_overlap]} 
        else:
            print('Bottom image is shifted towards the left by %i pixels'
                  %(int_offset_col))
            int_offset_col = x_min
            x_l += int_offset_col
            top_extension = (top, dummy_top)
            bot_extension = (dummy_bot, bot)
            o_top_extension = (overlap_top, dummy_overlap)
            o_bot_extension = (dummy_overlap, overlap_bot)
            print('Extending bottom left and top right to match shape after correlation')
            # parts of stitch center not averaged, will be appended later
            stitch_left = overlap_top[:,dummy[0]:x_l,:] # left overhang of avg
            stitch_right = overlap_bot[:,-int_offset_col -dummy[1]: overlap_bot.shape[1]-dummy[1],:]
            # effective offset is diminished by this value since we added signal to the other side 
            # than with the function extend_cols
            print(stitch_left.shape, stitch_right.shape)
            print('CRITICAL'*100)
            new_overhang = [int_offset_col, 0] # save that dummy was added to bottom left for next correlation
            print('Bottom left is expanded with dummy signal')
            connections = {'left': [top_overlap],
                           'right':[top.shape[0]]}
        
        
        top = np.concatenate(top_extension, axis=1)
        bot = np.concatenate(bot_extension, axis=1)
        overlap_top = np.concatenate(o_top_extension, axis=1)
        overlap_bot = np.concatenate(o_bot_extension, axis=1)
        
        # top = np.delete(top, top_slice, axis=1)
        # bot = np.delete(bot, bot_slice, axis=1)
        # overlap_top = np.delete(overlap_top, top_slice, axis=1)
        # overlap_bot = np.delete(overlap_bot, bot_slice, axis=1)
    else:
        print('No x-offset detected')
        connections = {'left': [top_overlap],
                       'right':[top_overlap]}
        stitch_left = stitch_right = np.empty((overlap_top.shape[0], 0, overlap_top.shape[-1]))
        new_overhang = [0, 0]
    # do not delete cols, vital for the column stitching step 
    
    
    print('xmin: ', x_min, 'xstart: ', xstart)
    # reduced avergaing area (only where signal is present)
    if _plot:
        test = np.concatenate((overlap_top, overlap_bot), axis=0)
        plt.imshow(test[:,:,ch], vmax=vmax_var)
        plt.title('original averaging area %s'%offset)
        plt.show()
        test = np.concatenate((overlap_top[:,x_l:x_max_data,:], overlap_bot[:,x_l:x_max_data,:]), axis=0)
        plt.imshow(test[:,:,ch], vmax=vmax_var)
        plt.title('reduced averaging area %s'%offset)
        plt.show()
    
    weight_list_x = lin_weights(overlap_top.shape[0])
    stitch_center = np.full((overlap_top.shape[0], top.shape[1], overlap_top.shape[2]), np.NaN)
    # avg is limited by offsets 
    
    for i in range(0, overlap_top.shape[0]):   # start at the top, place the bottom image on top of it
        # averaging the ith row with weights
        stacked_rows = np.stack((overlap_top[i,x_l:x_max_data,:],overlap_bot[i,x_l:x_max_data,:]), axis=0)
        avg_rows = np.average(stacked_rows, axis=0, weights=weight_list_x[i])   # average of each row
        stitch_center[i, x_l:x_max_data, :] = avg_rows
   
    #%% extending the averaging  (not mandatory)
    # This is not trivial, if we just extend it by the overhanging signal, the image appears too bright
    if _plot:
        fig, ax = plt.subplots(2, 1)
        ax[0].imshow(stitch_center[:,:,ch], vmax=vmax_var)
        ax[0].set_title('stitch center uncompleted %s')
     
   
    stitch_center[:, dummy[0]:x_l, :] = stitch_left
    # if stitch_right.shape[1] != 0:
    stitch_center[:, x_max_data:x_max_data+int_offset_col, :] = stitch_right
    if _plot: 
        ax[1].imshow(stitch_center[:,:,ch], vmax=vmax_var)
        ax[1].set_title('stitch center expanded')
        plt.show()
    
    #%% 
    stitch = np.row_stack((top, stitch_center, bot))
    if _plot:
        plt.imshow(stitch[:,:,ch], vmax=vmax_var)
        plt.show()
    
    return stitch, new_overhang, connections

def extend(image, length, axis=1):
    """
    Extends the input image by adding dummy signal to the right.
    """
    diff = length - image.shape[axis]
    shape_ = np.array(image.shape)
    if diff > 0:
        shape_[axis] = diff
        extension = np.full(shape_, np.NaN)
        full_extension = np.concatenate((image, extension), axis=axis)
    else:
        full_extension = image
    return full_extension

def add_cols(image, dummy):
    shape_ = np.array(image.shape)
    extension_l =  np.full((shape_[0], dummy[0], shape_[-1]), np.NaN)
    extension_r = np.full((shape_[0], dummy[1], shape_[-1]), np.NaN)
    image = np.concatenate((extension_l, image, extension_r), axis=1)
    return image

def adjust_rows(im_l, im_r):
    """
    Extends the row image by adding zeros signal to the bottom.
    """
    diff = im_r.shape[0] - im_l.shape[0]
    if diff != 0:
        if diff > 0:
            dummy = np.full((diff, im_l.shape[1], im_l.shape[2]), np.NaN)
            im_l = np.concatenate((im_l, dummy), axis=0)
        else:
            dummy = np.full((abs(diff), im_r.shape[1], im_r.shape[2]), np.NaN)
            im_r = np.concatenate((im_r, dummy), axis=0)
    return im_l, im_r


def attach_cols(list_l, list_r, overlap, sigma_interval, channel_list = None,
                _plot = False):
    """
    Function, which attaches two column images based on their dummy signal and
    cross-correlation of the overlapping region.

    Attach two stitched column-blocks (left/right) with:
    1) robust vertical offset estimation across slices
    2) iterative coarse alignment via dummy padding
    3) final horizontal blending in the overlap region

    Parameters
    ----------
    list_l : dict
        the left image data including 'img', 'dummy', 'connection' keys
    list_r : dict
        the right image data including 'img', 'dummy', 'connection' keys
    overlap : int
        Pixel overlap of adjacent images. Must not be exactly known. The region used for averaging.
    sigma_interval : int
        confidence interval used to accept offset values.
    channel_list : list, optional
        If channels is passed to the function, only the channels specified will
        be convoluted. The default is None --> all channels are convoluted.
    _plot : boolean, optional
        If True, intermediate steps are plotted. The default is False.
    Returns
    -------
    new_image : array
        The stitched image of the two columns.
    """
    list_l['img'], list_r['img'] = adjust_rows(list_l['img'], list_r['img'])    

    d_list, slice_idx_list, dummy_list = find_dummy_indices(list_l, list_r)
    logger.debug(slice_idx_list)
    new_image, correlations, overlap_list = dummy_correlation(list_l, list_r, overlap,
                                                   d_list, slice_idx_list, dummy_list, channel_list = channel_list)
    
    """ we need to find the best MEAN correlation since the images need to be attached the way they are
        we can't change their relative placement anymore after the row stitching    
    """
    logger.debug(correlations)
    mean_corr = mean_corr_no_outliers(correlations, sigma_interval)
    logger.debug(correlations)
    logger.debug('NEW MEAN', mean_corr)
    
    # plt.imshow(new_image[:,:,ch], vmax=vmax_var)
    
    # move an entrie image by the mean_corr[0] value up/downwards
    # offset[0] < 0: left image is translated downwards by |offset[0]| pixels
    # offset[0] > 0: left image is translated upwards by offset[0] pixels
    
    #%% ADD DUMMY TO FIX 
    tries = 0
    """ find iteratively the best offset """
    while abs(mean_corr[0]) >= 1 and tries < 5:
        logger.debug(('TRY %s '%tries)*10)
        img_l, img_r =  list_l['img'], list_r['img']
        logger.debug(img_l.shape)
        int_offset = int(mean_corr[0])
        dummy_length = abs(int_offset)
        dummy_l = np.full((dummy_length, img_l.shape[1], img_l.shape[2]), np.NaN)
        dummy_r = np.full((dummy_length, img_r.shape[1], img_r.shape[2]), np.NaN)
        if int_offset != 0:
            if int_offset > 0:
                l_extension = (dummy_l, img_l)
                r_extension = (img_r, dummy_r)
                text = 'added %i rows to top left'%dummy_length
                logger.debug(text)
                # new indices
                for key in list_l['connection']:
                    list_l['connection'][key] = np.add(list_l['connection'][key], dummy_length)
            else:
                l_extension = (img_l, dummy_l)
                r_extension = (dummy_r, img_r)
                text = 'added %i rows to top right'%dummy_length
                logger.debug(text)
                for key in list_r['connection']:
                    list_r['connection'][key] = np.add(list_r['connection'][key], dummy_length)
        
            list_l['img'] = np.concatenate(l_extension, axis=0)
            list_r['img'] = np.concatenate(r_extension, axis=0)
            
        logger.debug(list_l['img'].shape)
        # recalc slices and dummies again, in case offset is very large, these can change!
        d_list, slice_idx_list, dummy_list = find_dummy_indices(list_l, list_r)
        new_image, corr_new, overlap_list = dummy_correlation(list_l, list_r, overlap, 
                                                              d_list, slice_idx_list, dummy_list,
                                                              channel_list = channel_list)        
        # new (more precise correlations)
        logger.debug(overlap_list)
        mean_corr = mean_corr_no_outliers(corr_new, sigma_interval)
        logger.debug('_'*500)
        logger.debug(mean_corr)
        logger.debug('_'*500)
        if _plot:
            plt.imshow(new_image[:,:,ch], vmax=vmax_var)
            plt.show()
        tries+=1
        
    mean_corr[np.isnan(mean_corr)] = 0
    logger.debug('-'*50, 'Found best correlation with setting %s'%mean_corr, '-'*50)
    """ after finally adjusting the relative offset, we only need to calculate the average (as already done before)
        for all slices stored in 'slice_idx'!
    """  

    new_image = average_columns(new_image, mean_corr, overlap, slice_idx_list, overlap_list)
    return new_image

def find_dummy_indices(list_l, list_r):
    connections_l = list_l['connection']['right']
    connections_r = list_r['connection']['left']
    img_l = list_l['img']
    r_idx = 1
    d_list = []
    slice_idx_list = [0]
    dummy_list = []
    max_idx = len(list_r['dummy'])-1 
    for i, idx in enumerate(connections_l[1:]):    # first entry is 0, irrelevant
        # dummy betweeen next data points
        j = i
        dummy_idx = r_idx-1    # dummy idx in the list is always -1 compared to the slice index
        while idx > connections_r[r_idx] and r_idx < max_idx:
            if connections_r[r_idx] not in slice_idx_list:
                slice_idx_list.append(connections_r[r_idx])
                d_list.append(list_l['dummy'][j][1] + list_r['dummy'][dummy_idx][0])
                dummy_list.append({'left': list_l['dummy'][j][1],
                                   'right': list_r['dummy'][dummy_idx][0]})
            r_idx += 1
            dummy_idx += 1
        next_idx  = min(idx, connections_r[r_idx])      # is necessary due to the second condition in the while loop!
        if next_idx not in slice_idx_list:
            d_list.append(list_l['dummy'][j][1] + list_r['dummy'][dummy_idx][0])
            slice_idx_list.append(next_idx)
            dummy_list.append({'left': list_l['dummy'][j][1],
                               'right': list_r['dummy'][dummy_idx][0]})
        # if r_idx < max_idx:
        #     r_idx += 1
   
    if idx not in slice_idx_list:
        slice_idx_list.append(idx)
        d_list.append(list_l['dummy'][-1][1] + list_r['dummy'][-1][0])
        dummy_list.append({'left': list_l['dummy'][-1][1],
                           'right': list_r['dummy'][-1][0]})
    slice_idx_list.append(img_l.shape[0])
    d_list.append(list_l['dummy'][-1][1] + list_r['dummy'][-1][0])
    dummy_list.append({'left': list_l['dummy'][-1][1],
                               'right': list_r['dummy'][-1][0]})
    return d_list, slice_idx_list, dummy_list

# independent of scan direction, one only needs to know which is the leaft and right image
def dummy_correlation(list_l, list_r, overlap, d_list, slice_idx_list, dummy_list,
                      channel_list = None, average=False):
    # calc dummy areas and indices
    img_l = list_l['img']
    img_r = list_r['img']
    
    d_max_idx = np.argmax(d_list)
    d_max = d_list[d_max_idx]
    

    # move left image to the right such that no empty pixels in between images
    new_image = np.empty((img_l.shape[0], img_l.shape[1]+img_r.shape[1]-d_max, img_l.shape[2]))
    correlations = []
    overlap_list = [] # x index where overlap starts
    for i, idx in enumerate(slice_idx_list[1:]):
        spare_pixels = d_max - d_list[i]
        remove_l = spare_pixels // 2
        remove_r = remove_l + spare_pixels % 2  
        y_slice = np.s_[slice_idx_list[i]:idx]        
        print(y_slice)
        # left part 
        # clear empty inbetween plus the spare pixels 
        img_start_idx = dummy_list[i]['right']+remove_r
        x_slice_l = np.s_[0: img_l.shape[1]-(dummy_list[i]['left']+remove_l)]
        img_l_cleared = img_l[y_slice, x_slice_l, :]
        x_slice_r = np.s_[img_start_idx:]
        img_r_cleared = img_r[y_slice, x_slice_r,:]
        
        
        corr = max_correlation(img_l_cleared[:,-overlap:, :],
                               img_r_cleared[:,:overlap, :], channels=channel_list)
        correlations.append(corr)
            
        new_image[y_slice, 0:img_l_cleared.shape[1],:] = img_l_cleared
        # right part  
        new_image[y_slice, img_l_cleared.shape[1]: ,:] = img_r_cleared
        overlap_list.append(img_l_cleared.shape[1])
        

        # plt.title(overlap_list[-1])
        # plt.imshow(new_image[y_slice,:,0], vmax=vmax_var)
        # plt.show()
        
    return new_image, correlations, overlap_list



def average_columns(image, mean_offset, overlap, y_slice_idx_list, overlap_idx_list, _plot = False):
    # move left image to the right such that no empty pixels in between images
    
    """
    if mean_offset != 0:
        if mean_offset > 0:
            pass
            # left image is too far left
            # cut off pixels from left of the left overlap and append them to 
            # the left image
            # same for the right with the right side
        else:
            pass
            # left image is too far right 
            # cut off most inner pixel and bin them (this case is easer but 
            # will appear not so often)
        """
        
    stitches = []
    for i, idx in enumerate(y_slice_idx_list[1:]):
        y_slice = np.s_[y_slice_idx_list[i]:idx]        
        print(y_slice, overlap_idx_list[i])
        im_r = image[y_slice, overlap_idx_list[i]:, :]
        im_l = image[y_slice, :overlap_idx_list[i], :]

        im_l, im_r, overlap_l, overlap_r = adjust_x(im_l, im_r, -mean_offset, overlap)
        # Splitted image with corrected offset
        if _plot:
            fig, ax = plt.subplots(1, 4, sharey=True)
            ax[0].imshow(im_l[:,:,ch], vmax=vmax_var, aspect="equal")
            ax[1].imshow(overlap_l[:,:,ch], vmax=vmax_var, aspect="equal")
            ax[2].imshow(overlap_r[:,:,ch], vmax=vmax_var, aspect="equal")
            ax[3].imshow(im_r[:,:,ch], vmax=vmax_var, aspect="equal")
            plt.show()
        
        weight_list = lin_weights(overlap_l.shape[1])
        stitch_center = np.full((im_l.shape[0], overlap_l.shape[1], im_l.shape[2]), np.NaN)
        
        for i in range(0, overlap_l.shape[1]):   # start at the top, place the bottom image on top of it
            # averaging the ith row with weights
            stacked_cols = np.stack((overlap_l[:,i,:],overlap_r[:,i,:]), axis=1)
            avg_cols = np.average(stacked_cols, axis=1, weights=weight_list[i])   # average of each row
            stitch_center[:, i, :] = avg_cols
        
        stitched = np.concatenate((im_l, stitch_center, im_r), axis=1)
        # if _plot:
        #     plt.imshow(stitch_center[:,:,ch], vmax=vmax_var)
        #     plt.title('stitch center uncompleted')
        #     plt.show()
        # if _plot:
        #     plt.imshow(stitched[:,:,ch], vmax=vmax_var)
        #     plt.title('stitched column')
        #     plt.show()
        stitches.append(stitched)
    
    full_image = np.vstack(stitches)
    return full_image

def mean_corr_no_outliers(correlations: np.ndarray, sigma_interval):
    """
    This function calculates the mean correlation while removing outliers based on a specified sigma interval.
    Attention: modifies the input array in place.
    Parameters
    ----------
    correlations
    sigma_interval

    Returns
    -------

    """
    # assume normal distribution to clear too large deviations
    # https://www.kdnuggets.com/2017/02/removing-outliers-standard-deviation-python.html
    # remove the outlier points by eliminating any points that were above (Mean + 2*SD) and any points below (Mean - 2*SD)
    correlations = remove_outliers(correlations, sigma_interval)
    mean_corr = np.nanmean(correlations, axis=0)
    print(correlations)
    return mean_corr

def remove_outliers(correlations, sigma_interval = 2):
    """
    This function removes outliers from a given set of correlations based on a specified sigma interval.
    Attention: modifies the input array in place.
    
    Parameters:
    correlations (numpy.ndarray): An array of correlations to be processed.
    sigma_interval (int, optional): A sigma interval to determine the boundaries of what is considered an outlier.
    
    Returns:
    numpy.ndarray: An array of correlations with outliers removed.
    
    """
    print(('%s'%sigma_interval)*100)
    mean_corr = np.nanmean(correlations, axis=0)
    sd = np.std(correlations, axis=0)
    for corr_array in correlations:
        for i, value in enumerate(corr_array):
            if (value < mean_corr[i] - sigma_interval * sd[i] or
                value > mean_corr[i] + sigma_interval * sd[i]):
                print('Standard deviation too large', value)
                corr_array[i] = np.NaN    
    return correlations

def translate_offset_to_text(offset):
    """
    This function translates a 2-element tuple representing the x and y offset of an image into a text description.
    The x offset is the number of pixels the image has been shifted to the right or left.
    The y offset is the number of pixels the image has been shifted up or down.

    Parameters:
    offset (tuple): a 2-element tuple representing the x and y offset of an image.
                    The first element represents the y offset and the second element represents the x offset.

    Returns:
    None

    Example:
    translate_offset_to_text((-10, 20))
    Output: Images are translated with
            20 pixels to the right and
            10 pixels to the top

    """
    value_y = int(offset[0])
    if value_y > 0:
        y_word = '%i pixels to the bottom'%abs(value_y)
    elif value_y < 0: 
        y_word = '%i pixels to the top'%abs(value_y)
    else:
        y_word = 'no y-offset'
    value_x = int(offset[1])
    if value_x > 0:
        x_word = '%i pixels to the right'%abs(value_x)
    elif value_x < 0: 
        x_word = '%i pixels to the left'%abs(value_x)
    else:
        x_word = 'no x-offset'
    print('Images are translated with\n%s and\n%s'%(x_word,y_word))

def stitch_corr(data: dict, lookup_x: list, lookup_y: list, overlap_row: int,
                overlap_col: int, sigma_interval: float = 1,
                channel_list:list = None, mode: str = 'normal',
                ch: int=0, vmax_var: float = 2500, _plot=False) -> np.ndarray:
    """
    Stitch and correct the data.

    Parameters
    ----------
    data : dict
        Dictionary containing data with the format {x_position: {y_position: {'img': image_data}}}
    lookup_x : list
        List of x positions to stitch.
    lookup_y : list
        List of y positions to stitch.
    overlap_row : int
        The number of overlapping rows between images.
    overlap_col : int
        The number of overlapping columns between images.
    sigma_interval : int, optional
        The sigma interval for row correlation. The default is 1.
    channel_list : list, optional
        List of channels to use for stitching. If not provided, all channels will be used. The default is None.
    mode : str, optional
        The mode for row correlation. The default is 'normal'.
    ch : int, optional
        The channel to display in the plot. The default is 0. Only active if _plot is set to True.
    vmax_var : int, optional
        The maximum value for the displayed plot. The default is 2500. Only active if _plot is set to True.
    _plot : bool, optional
        Whether to display a plot or not. The default is False.

    Returns
    -------
    col_stitch : np.ndarray
        The stitched image data.
    """
    # Checking the Channel list entries for possible overflows
    if channel_list is not None:
        xpos, ypos = lookup_x[0], lookup_y[0]
        channels = data[xpos][ypos]['img'].shape[-1]
        outliers = [x for x in channel_list if x >= channels]
        if outliers:
            showerror('Indices out of range', 'Please consider removing these indices %s'%outliers
                      +' for your channel correlation data.')
            return
    start = time.process_time()
    offsets = row_correlation(data, lookup_x, lookup_y, overlap_row, mode,
                              sigma_interval, channel_list = channel_list)
    x_stitch_list = []
    start = time.process_time()
    for j, xpos in enumerate(lookup_x):
        # colum stitching for each y
        stitch = data[xpos][lookup_y[0]]['img']
        dummy_added = [0,0]
        connection_indices = {'left':[0], 'right':[0]}
        dummy_list = [np.array(dummy_added)]
        loop = j*len(lookup_y[:-1])
        for ii, ypos in enumerate(lookup_y[:-1]):
            print('-'*50 + 'row%i'%ii + '-'*50)
            overlap_top = data[xpos][ypos]['img'][-overlap_row:,:,:]    # overlap without dummy data, using raw data
            bot = data[xpos][lookup_y[ii+1]]['img']
            overlap_bot = bot[:overlap_row,:,:]
            # if offsets is None:
            #     offset = max_correlation(overlap_top, overlap_bot, channels=channel_list)  # correlation of raw signals, w/o dummy data
            # else:
            offset = offsets[ii+loop]
            if _plot:
                before_corr = np.concatenate((overlap_top, overlap_bot), axis=0)
                plt.imshow(before_corr[:,:,ch], vmax=vmax_var)
                plt.title('data before correlation')
                plt.show()    
            stitch, row_overhang, connections = correct_y_offset(stitch,
                                                                 bot,
                                                                 offset,
                                                                 overlap_row,
                                                                 dummy_added,
                                                                 _plot=_plot)
            dummy_added = np.add(dummy_added, row_overhang)
            for key in connections:
                connection_indices[key] += connections[key]
            
            dummy_list += [dummy_added]
            # dummy_added is the total dummy signal added to the latest stitching image
            # [0]: dummy added to the bottom left image 
            # important info for the averaging procedure, sets its limits
        for dummy in dummy_list[:-1]:
            old_dummy = dummy.copy()
            dummy[0] += dummy_added[1] - old_dummy[1]
            dummy[1] += dummy_added[0] - old_dummy[0]
        
        x_stitch_list.append({'img': stitch,
                              'connection': connection_indices,
                              'dummy': dummy_list,
                              'col': j})
        if _plot:
            plt.imshow(stitch[:,:,ch], vmax=vmax_var)
            plt.savefig(spath+ '/column%i_stitch_extensions.png'%j, dpi=400)
    print('TIME FOR ROW STITCHING: ', time.process_time()-start)
    #%% rows done
    im_r = x_stitch_list[0]['img']
    for i, entry in enumerate(x_stitch_list[1:]):
        im_l, im_r = adjust_rows(entry['img'], im_r)    # opposite way for oppsoite scan direction
        im_r = np.concatenate((im_l, im_r), axis=1)

    
    print('-'*100, im_r.shape, '-'*100, )
    if _plot:
        plt.imshow(im_r[:,:,ch], vmax=vmax_var)
        plt.savefig(spath+'/rows_stitched_with_extensions.png', dpi=400)
        plt.show()
    
    for i, list_entry in enumerate(x_stitch_list[1:]):
        col_stitch = attach_cols(list_entry, x_stitch_list[i], overlap_col,
                                 sigma_interval, channel_list = channel_list)
        list_entry['img'] = col_stitch # attach results 
    
    if _plot:
        # STITCH IMAGE
        plt.imshow(col_stitch[:,:,ch], vmax=vmax_var)
        plt.savefig(spath+'/dummy_removed01.png', dpi=400)
    
    return col_stitch
    

#%% END OF FUNCTIONS
if __name__ == '__main__':
    overlap_row = 90
    overlap_col = 90
    data = 'new'
    if data == 'RS':
        ch = 2
        channel_list = None
        vmax_var = 1500
        subfolder = ''
    elif data == 'new':
        ch = 0
        vmax_var = 1500
        channel_list = None
        subfolder = ''
        mode_ = 'sigma mean'
    else:
        ch = 1
        channel_list = [1]
        vmax_var = 10
        subfolder = r'/SHG'
   
    
    _plot = True
    sigma = 2
    
    dpath = r"/Users/mkunisch/Nextcloud/Manuel_BA/Leber_reduzierter Spektralumfang/pos1_reduced/"+subfolder
    spath = r'/Users/mkunisch/Nextcloud/Manuel_BA/Leber_reduzierter Spektralumfang/pos1_reduced/'+subfolder

    #%% STITCHING
    # data, lookup_x, lookup_y = stitching.stitch_load(dpath)

    # stitch_result = stitch_corr(data, lookup_x, lookup_y, overlap_row, overlap_col,
    #                             channel_list = channel_list, mode = 'mean',
    #                             sigma_interval=1)
         
    
    stitch_data = stitching.stitch_load(dpath)                       
    stitch_result = stitch_corr(*stitch_data, overlap_row, overlap_col,
                                channel_list = channel_list, mode = 'sigma mean',
                                ch = ch,
                                sigma_interval=sigma, _plot=_plot,
                                vmax_var = vmax_var)
    
    plt.imshow(stitch_result[:,:,ch], vmax=vmax_var)
    plt.savefig(spath+'/stitch_full_%isigma.png'%sigma, dpi=400)

    tiff.imwrite(spath+'/stitch_full_%isigma.tif'%sigma, stitch_result[:,:,ch])

