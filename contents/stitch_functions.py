# -*- coding: utf-8 -*-
"""
Created on Sun Jul  3 18:42:41 2022

@author: Manuel
"""

import os
import re
from typing import List, Tuple, Dict

import matplotlib.pyplot as plt
import numpy as np
from scipy import interpolate
from scipy.optimize import curve_fit
from skimage import io  # READIN TIF STACKS

import contents.rolling_ball_mask as rb


def stitch_load(data_path: str, base_name: str = None,
                filetype: str = '.tif', **kwargs) ->  Tuple[Dict, List, List]:
    """Loads a set of images from a folder and prepares them for stitching.

    Args:
        data_path: The path of the folder containing the images.
        base_name: The name of the base image to use for stitching. If not specified,
            the function tries to automatically find the base image in the folder.
        filetype: The file extension of the images to load.
        **kwargs: Additional arguments to pass to the `stitch_pos_finder` function.

    Returns:
        tuple: A tuple containing three elements: (1) a dictionary containing the images and their
            positions, sorted by rows and columns, (2) a list of x-positions, and (3) a list of y-positions.

    Raises:
        None.

    This function loads a set of images from a folder and prepares them for stitching.
    It searches for images with the specified file extension in the folder and reads them
    using the `skimage.io.imread` function. The function then sorts the images into columns
    based on their x positions and into rows based on their y positions. The base image
    is used as a reference to determine the positions of the other images. The function 
    returns a dictionary containing the images and their positions, sorted by rows and columns
    as well as the lookup tables for the positions.
    """
    entries=os.listdir(data_path)
    entries = [x for x in entries if x.endswith(filetype)]
    data = {}
    remaining = []    # dummy for storage of remaining files in folder
    x_pos = []  # for lookup tables
    y_pos = []
    cols = 0
    if base_name is None:
        for entry in entries:
            _,_,_,base_name = stitch_pos_finder(entry, **kwargs)
            if base_name is not None:
                print(base_name)
                break
                
    for dname in entries: 
        root, ext = os.path.splitext(dname)
        print(root)
        if root.startswith(base_name):
            print(root)
            x, y, num, base = stitch_pos_finder(dname, **kwargs)
            if base is None:    # element does not match
                remaining.append(dname)
                print(dname)
                continue # jumps to the start of the loop
            print(dname)
            signal = io.imread(f'{data_path}/{dname}', is_ome=False)
            # reshaping 
            j = np.argmin(np.shape(signal))
            signal=np.moveaxis(signal,j,-1 )
            if x in data: 
                data[x].update({y: {'img':signal, 'number': num, 'raw_img': signal}}) # save for later access
                x_pos.append(x)
                y_pos.append(y)
            else:
                data.update({x: {y: {'img':signal, 'number': num, 'raw_img': signal}}})
                cols += 1   
                y_pos.append(y)
                x_pos.append(x)
            print(data.keys())
    print('x pos:', x_pos)
    lookup_x = sorted(set(x_pos))
    lookup_y = sorted(set(y_pos))
    
    print(lookup_x, lookup_y)
    y_images=[]
    # check if each dimension is the same
    for key in data:    # sorting and counting (cols and rows could probably be unordered)
        data[key] = dict(sorted(data[key].items()))
        y_images.append(len(data[key]))
    
    data = dict(sorted(data.items())) # sort cols
    
    rows= set(y_images)
    if len(rows) > 1:  # set removes all duplicates from list
        print('error: your data is lacking images')
        return
    else:
        print('Stich load succesful')
    return data, lookup_x, lookup_y

def stitch_pos_finder(dname: str, delimiter: str = '_', pos_key: str = 'pos') -> Tuple[int, int, str, str]:
    """
    Extracts position information from a filename using a delimiter and a key.

    Args:
        dname: The filename to extract position information from.
        delimiter: The delimiter used in the filename to separate different parts.
            Default is '_'.
        pos_key: The key used in the filename to indicate position information.
            Default is 'pos'.

    Returns:
        A tuple containing the x position (int), y position (int), image number (str),
        and base name (str) extracted from the filename. If any of the information cannot
        be extracted, the corresponding value is set to None.

    Raises:
        None.
    """
    part_names=dname.split(delimiter)
    # print(part_names)
    x = y = img_num = base = None
    for i, string in enumerate(part_names): 
        if string.casefold() == pos_key:  # format must be pos_x_y
            x=part_names[i+1]   #convention: first y then x in data name   
            y=part_names[i+2]
            img_num=part_names[-1]
            x_strip = x.lstrip("-").rstrip("_")
            y_strip = y.lstrip("-").rstrip("_")
            if x_strip.isdigit() and y_strip.isdigit():
                base = '_'.join(part_names[:i])
                x = int(x)
                y = int(y)
                break
        # Check for float number positions and remove possible file extensions with rstrip()
            elif re.sub("[^0-9]", "", x_strip).isdigit() and re.sub("[^0-9]", "", y_strip).isdigit():
                base = '_'.join(part_names[:i])
                x = re.sub("[^0-9.]", "", x)
                y = re.sub("[^0-9.]", "", y)
                # check for error that appears if pos is right next to the file extension
                while not x[-1].isdigit():
                    x = x[:-1]
                while not y[-1].isdigit():
                    y = y[:-1]
                x = float(x)
                y = float(y)
                break
            else:
                print(re.sub("[^0-9]", "", x_strip),  re.sub("[^0-9]", "", y_strip))
                print(re.sub("[^0-9]", "", x_strip).isdigit(),  re.sub("[^0-9]", "", y_strip).isdigit())
                print('wrong pos indicator. Neither int nor float')                  
    return x, y, img_num, base
    
def bin2d(a: np.array, K:int) -> np.array:
    """
    Binning 2D array by averaging non-overlapping blocks of size K x K.
    
    Args:
        a: 2D numpy array to be binned.
        K: Block size for binning.
    
    Returns:
        A 2D numpy array obtained by averaging non-overlapping blocks of size K x K.
    
    Raises:
        None.
    """
    m_bins = a.shape[0]//K
    n_bins = a.shape[1]//K
    return a.reshape(m_bins, K, n_bins, K).mean(3).mean(1)
    

def lin_weights(overlap: int, max_weight: float =1) -> list: 
    """
    Compute a list of linear weights to blend overlapping images.

    Args:
        overlap (int): The number of overlapping pixels between adjacent images.
        max_weight (float): The maximum weight assigned to the top image. Default is 1.
    
    Returns:
        weight_list (list): A list of linear weights for blending the overlapping images. Each element of the list is a 2-element list [w_top, w_bottom], representing the weight assigned to the top and bottom images, respectively.
    
    Raises:
        None.
    """
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

def stitch(data: dict, lookup_x: list, lookup_y: list, overlap_row: int, overlap_col: int,
           scan_direction_x: str ='left',
           scan_direction_y: str ='down',
           should_plot: bool = False) -> np.ndarray:
    """
    Stitch together a set of overlapping images in a grid pattern.
    
    Args:
        data (dict): A dictionary with keys as tuples of (x,y) coordinates and values as dictionaries with keys "img" and "number". "img" is a 2D numpy array of the image data and "number" is a unique identifier for the image.
        lookup_x (list): A list of x-coordinates to use for stitching. The order of this list determines the order in which the columns are stitched together.
        lookup_y (list): A list of y-coordinates to use for stitching. The order of this list determines the order in which the rows are stitched together.
        overlap_row (int): The number of rows of overlap between adjacent images in a row.
        overlap_col (int): The number of columns of overlap between adjacent images in a column.
        scan_direction_x (str): The direction to scan along the x-axis. Can be "left" or "right". Default is "left".
        scan_direction_y (str): The direction to scan along the y-axis. Can be "up" or "down". Default is "down".
        should_plot (bool): Whether to plot the intermediate stitched images during the stitching process. Default is False.
       
    Returns:
        np.ndarray: A 2D numpy array representing the final stitched image.
   
    Note:
    The images in the dictionary 'data' resp. the folder should be named such that if the scan_direction_x is 'left',
    the images with lower x-coordinates should come before the images with higher x-coordinates, and if the scan_direction_x is 'right',
    the images with higher x-coordinates should come before the images with lower x-coordinates. Similarly, if the scan_direction_y is 'up',
    the images with lower y-coordinates should come before the images with higher y-coordinates, and if the scan_direction_y is 'down',
    the images with higher y-coordinates should come before the images with lower y-coordinates.
    """
    weight_list_x = lin_weights(overlap_row)
    weight_list_y = lin_weights(overlap_col)
    # row stitching: column is fixed for each j loop. With every pass y advances 
    x_stitch_list = []
    if scan_direction_y != 'down':
        lookup_y = lookup_y[::-1]
    if scan_direction_x != 'left':
        lookup_x = lookup_x[::-1]
    len_x = len(lookup_x)
    for j in range(0, len(lookup_y)):
        # colum stitching for each y
        if j >= len_x:
            # no further columns exist
            break
        ystart = lookup_y[0]
        print('y: ', ystart)
        xpos = lookup_x[j]
        print('xpos: ', xpos)
        stitch_data = data[xpos][ystart]
        stitch = stitch_data['img'] # top image of stitching: start point of each row
        
        # print('start image for row stitching: ', stitch_data['number'])
        # now: y fixed 
        for ii, ypos in enumerate(lookup_y[1:]):      # iterate over each row (xpos)
            data_bottom = data[xpos][ypos]
            bottom = data_bottom['img']          # the entire bottom image of stitching
            image_top_ = stitch[:-overlap_row]         # top image w/o overlap
            image_bottom_ = bottom[overlap_row:]       # bottom image w/o overlap
            
            print('start to attach: ', data_bottom['number'])
            image_shape = image_top_.shape
            stitch_center = np.empty((overlap_row, image_shape[1] , image_shape[-1])) #save averaged data
            
            for i in range(0, overlap_row):   # start at the top, place the bottom image on top of it
                image_top = stitch[-overlap_row+i]     
                image_bottom = bottom[i]      # stitching overlap_rows
                stacked_rows = np.stack((image_top,image_bottom), axis=0)
                avg_rows = np.average(stacked_rows, axis=0, weights=weight_list_x[i])   # average of each row
                stitch_center[i] = avg_rows
            
            stitch = np.row_stack((image_top_, stitch_center, image_bottom_))
        x_stitch_list.append({'img': stitch, 'col': j})
    
    # Handling single row images with multi-columns
    if len(lookup_y) == 1:
        print('Detected single row image')
        for xpos in lookup_x[1:]:
            j+=1
            stitch_data = data[xpos][ystart]
            im = stitch_data['img']
            x_stitch_list.append({'img': im, 'col': j})
            
    

    stitch_y_data = x_stitch_list[0]
    stitch_y = stitch_y_data['img']   # right image
    print('start column stitching with column ', stitch_y_data['col'])
    print(len(x_stitch_list))
    ii=0
     
    add_slice = np.s_[:, :-overlap_col, :]
    current_slice = np.s_[:, overlap_col:, :]
    add_indices = np.arange(-overlap_col, 0)
    current_indices = np.flipud(add_indices + 1) * (-1)
    
    for j in x_stitch_list[1:]:
        ii+=1
        print('start to attach col', j['col'])
        to_add = j['img'] # left img (for this dara set)
        to_add_ = to_add[add_slice]
        current_ = stitch_y[current_slice]    # right image (w/o overlap)
        image_shape = to_add_.shape
        stitch_center = np.empty((image_shape[0], overlap_col , image_shape[-1])) #save averaged data
        
        
        for i, add_index in enumerate(add_indices):   # we move the right image to the left; the left image must have the largest weight at the start
            image_to_add = to_add[:,add_index , :]  # here: start with the most-left pixel (REVERSED ORDER!!!), which is superposed with the 0 th pixel of the left image
            image_current = stitch_y[:,current_indices[i] , :] 
            stacked_cols = np.stack((image_to_add, image_current), axis=1)  
            avg_cols = np.average(stacked_cols, axis=1, weights=weight_list_y[i]) # average of each row
            stitch_center[:,i,:] = avg_cols
        stitch_y = np.column_stack((to_add_, stitch_center, current_))  # stitched data
    return stitch_y

        
def create_intensity_correction(D, mode, fit_mode, 
                                x_custom, y_custom):
        """
        Creates an intensity correction matrix to correct for uneven illumination in an image.
    
        Parameters
        ----------
        D : numpy array
            Input 2D image array to be corrected.
        mode : str
            Correction mode to be used. Can be one of 'Fit' or 'Interpolation'. 
            If 'Fit', fits a smoothing function to the image data to obtain the correction matrix. 
            If 'Interpolation', performs a binning and interpolation approach to obtain the correction matrix.
        fit_mode : str
            If mode is 'Fit', specifies the type of function to be used for fitting. Can be one of 'linear',
            'quadratic', or 'gaussian'.
        x_custom : int, optional
            If mode is 'Fit' and fit_mode is not 'gaussian', the x-coordinate of the custom center
            to be used for fitting. Defaults to None.
        y_custom : int, optional
            If mode is 'Fit' and fit_mode is not 'gaussian', the y-coordinate of the custom center
            to be used for fitting. Defaults to None.
    
        Returns
        -------
        C : numpy array
            Intensity correction matrix.
    
        Raises
        ------
        ValueError
            If mode is not 'Fit' or 'Interpolation', or if fit_mode is not 'linear', 'quadratic', or 'gaussian'.
    
        Notes
        -----
        If mode is 'Fit', the function fits a smoothing function to the image data to obtain the
        correction matrix.
        The type of function to be used for fitting can be specified with the fit_mode parameter.
        The available options are 'linear', 'quadratic', and 'gaussian'. If fit_mode is not 'gaussian',
        a custom center can be specified using the x_custom and y_custom parameters.
    
        If mode is 'Interpolation', the function performs a binning and interpolation approach 
        to obtain the correction matrix. 
        """
        D_max = np.amax(D)
        D_fit = D.ravel() # prepare for fit: ravel data as optimize only fits curves 
        shape_data = np.shape(D)
        px_x = shape_data[1] // 2
        px_y = shape_data[0] // 2

        
        if mode == 'Fit':
            print('Rolling ball correction: fit mode ')
            x = np.arange(0, shape_data[1], 1)
            y = np.arange(0, shape_data[0], 1)
            X, Y = np.meshgrid(x, y)
            if fit_mode == 'linear':
                print('Applying linear intensity correction')
                initial_guess = ((shape_data[1]-1)/2, (shape_data[0]-1)/2, D_max, -2)
                pred_params, uncert_cov_r = curve_fit(rb.linear, (X,Y), D_fit, p0=initial_guess)
                if x_custom is None:
                    predicted_data = rb.linear((X,Y), *pred_params).reshape(shape_data[0],shape_data[1]) # * indicates list of arguments
                else:
                    xc = x_custom + shape_data[1]/2
                    yc = y_custom + shape_data[0]/2
                    print('Utilizing custom center at x %f and y %f'%(xc,yc))
                    red_params = pred_params[2:]
                    predicted_data = rb.linear((X,Y), xc, yc, *red_params).reshape(shape_data[0],shape_data[1]) # * indicates list of arguments
                N = np.full_like(predicted_data, np.amax(predicted_data))   # normalization matrix
            elif fit_mode == 'quadratic':
                print('Applying quadratic intensity correction in r')
                initial_guess = ((shape_data[1]-1)/2, (shape_data[0]-1)/2, D_max, -.1)
                pred_params, uncert_cov_r = curve_fit(rb.quadratic, (X,Y), D_fit, p0=initial_guess)
                if x_custom is None:
                    predicted_data = rb.quadratic((X,Y), *pred_params).reshape(shape_data[0],shape_data[1]) # * indicates list of arguments
                else:
                    xc = x_custom + shape_data[1]/2
                    yc = y_custom + shape_data[0]/2
                    predicted_data = rb.quadratic((X,Y), xc, yc, *pred_params[2:]).reshape(shape_data[0],shape_data[1]) # * indicates list of arguments
                N = np.full_like(predicted_data, np.amax(predicted_data))   # normalization matrix
            else:
                # gaussian
                # scipy optimize function expects the independent variables (x & y) as a single 2xN array
                print('Applying gaussian intensity correction')
                initial_guess = ((shape_data[1]-1)/2, (shape_data[0]-1)/2, 1e-4, 1e-4, D_max)
                pred_params, uncert_cov = curve_fit(rb.gaussian, (X,Y), D_fit, p0=initial_guess)   # fit the "x-data" (X and Y) to the "y-data" (image data) as pseudo 1D-fit
                print('Offset: ', pred_params[0], ' ', pred_params[1], '\nfactors: ', pred_params[2:])
                #reshape fitted data to image
                if x_custom is None:
                    predicted_data = rb.gaussian((X,Y), *pred_params).reshape(shape_data[0],shape_data[1]) # * indicates list of arguments
                else:
                    xc = x_custom + shape_data[1]/2
                    yc = y_custom + shape_data[0]/2
                    predicted_data = rb.gaussian((X,Y), xc, yc, *pred_params[2:]).reshape(shape_data[0],shape_data[1]) # * indicates list of arguments
                   
                N = np.full_like(predicted_data, np.amax(predicted_data))   # normalization matrix
            C = np.divide(N, predicted_data)
            correction_params = pred_params # xc, yc, a, b, A
            if x_custom is not None:
                offset_x = x_custom
                offset_y = y_custom
            else:
                offset_x = round(np.abs(pred_params[0])-shape_data[1]/2)
                offset_y = round(np.abs(pred_params[1])-shape_data[0]/2)
        else:   # interpolation
            print('Applying interpolated intensity correction')
            size = 64
            D_bin = bin2d(D, size)
            
            N_bin = np.full_like(D_bin, 1)
            C_bin = np.divide(N_bin, D_bin/np.amax(D_bin))
            
            
            x = np.linspace(0, 1, C_bin.shape[0])
            y = np.linspace(0, 1, C_bin.shape[1])
            f = interpolate.interp2d(y, x, C_bin, kind='cubic')
            
            x2 = np.linspace(0, 1, shape_data[0])
            y2 = np.linspace(0, 1, shape_data[0])
            C = f(y2, x2)
            C = C/np.amax(C)
            
            D_interpol = 1/C
            predicted_data = D_interpol
            max_i = np.unravel_index(np.argmax(D_interpol), D_interpol.shape)
            print(max_i)
            correction_params = None
            offset_x = round(np.abs(max_i[1])-shape_data[1]/2)
            offset_y = round(np.abs(max_i[0])-shape_data[0]/2)
        return C, offset_x, offset_y, px_x, px_y, correction_params, predicted_data

def correction_from_txt(mode, params, shape_y, shape_x):
    shape_y = int(shape_y)
    shape_x = int(shape_y)
    x = np.arange(0, shape_x, 1)
    y = np.arange(0, shape_y, 1)
    X, Y = np.meshgrid(x, y)
    fn = getattr(rb, mode)
    model = fn((X,Y),*params)
    print(model.shape)
    print(shape_y, shape_x)
    model = model.reshape((shape_y,shape_x))
    N = np.full_like(model, np.amax(model))   # normalization matrix
    C = np.divide(N, model)
    return C, model

def intensity_mask(C, mask_type, strength, offset_x, offset_y):
    if mask_type == 'circular mask':
        mask = rb.lorentzian(C, offset_x, offset_y, strength)
        # replaced with Lorentian type function 
    elif mask_type == 'diagonal mask':
        mask = rb.rect_mask(C, offset_x, offset_y, strength)
    else:
        mask = rb.rect_mask2(C, offset_x, offset_y, strength)
    C = C*mask 
    C = C/np.amax(C)
    print('Initialized %s'%mask_type)
    return C, mask
 #%%
def remove_nan_edges(hyper_img):
    try:
        y, x, c = hyper_img.shape
    except ValueError:
        y, x = hyper_img.shape
        hyper_img = hyper_img[:,:,np.newaxis]
        
    upper_bound = 0
    lower_bound = y-1
    right_bound = x-1
    
    mid_x = x//2
    mid_y = y//2
    
    l_r_bounds = []
    # Checking the top, bottom, left and right halves for consecutive NaNs
    for i in range(0, mid_y):
        print(i)
        # iterating the rows from the top
        if np.isnan(hyper_img[i, :, 0]).any():      # it is sufficent to check for HS axis 0
            nan_row = np.isnan(hyper_img[i, :, 0])
            nan_idx = np.where(nan_row)[0]
            nan_number = len(nan_idx)  # amount of NaNs in the row
            # checking for NaN at the row edges 
            if nan_number > mid_x:
                # if more NaNs in a row than half the image length automatically
                # discard the row
                upper_bound +=1
            else:
                consecutive_nans = split_consecutive_indices(nan_idx)
                if consecutive_nans[0][0] != 0 and consecutive_nans[-1][-1] != right_bound:
                    # Rather delete the row if the NaN is not at the edge of a column
                    upper_bound +=1
                    continue
                crit_idx = [item[0] for item in consecutive_nans[1:]] + [item[-1] for item in consecutive_nans]
                nan_cols = min([len(np.where(np.isnan(hyper_img[:, idx, 0]))[0]) for idx in crit_idx])
                if nan_cols <= nan_number:
                    upper_bound += 1
                    # still delete rows if minimum amout of nans in a column is
                    # < than NaNs in a rows because otherwise more pixels would be lost!
                else:
                    # Canidates for columns to remove
                    l_r_bounds.append(consecutive_nans[0][-1])
                    print('Discarded rows 0 - %i'%i)
                    break
        else:
            break
    # Repeat the same for the bottom
   
    for i in reversed(range(mid_y, y)):
        if np.isnan(hyper_img[i, :, 0]).any():
            nan_row = np.isnan(hyper_img[i, :, 0])
            nan_idx = np.where(nan_row)[0]
            nan_number = len(nan_idx)
            if nan_number > mid_x:
                lower_bound -= 1
            else:
                consecutive_nans = split_consecutive_indices(nan_idx)
                if consecutive_nans[0][0] != 0 and consecutive_nans[-1][-1] != right_bound:
                    # Rather delete the row if the NaN is not at the edge of a column
                    lower_bound -=1
                    continue
                crit_idx = [item[0] for item in consecutive_nans[1:]] + [item[-1] for item in consecutive_nans]
                nan_cols = min([len(np.where(np.isnan(hyper_img[:, idx, 0]))[0]) for idx in crit_idx])
                if nan_cols <= nan_number:
                    lower_bound -= 1
                    # still delete rows if minimum amout of nans in a column is
                    # < than NaNs in a rows because otherwise more pixels would be lost!
                else:
                    # Canidates for columns to remove
                    l_r_bounds.append(consecutive_nans[-1][0])
                    print('Discarded rows %i- %i'%(y, i))
                    break
        else:
            break
    hyper_img = hyper_img[upper_bound:lower_bound+1, :, :]
        
    if not np.isnan(hyper_img).any():
        return hyper_img
    if l_r_bounds:
        l_r_bounds = np.array(list(set(l_r_bounds)))
        try:
            l_bound = np.amax(l_r_bounds[l_r_bounds <= mid_x])
        except ValueError:
            l_bound = 0
        try:
            r_bound = np.amin(l_r_bounds[l_r_bounds >= mid_x])
        except ValueError:
            r_bound = right_bound
        hyper_img = hyper_img[:, l_bound:r_bound+1, :]
    # Checking for remaining NaNs in columns
    remaining_nan = np.where(np.isnan(hyper_img[:,:,0]).any(axis=0))[0]
    if len(split_consecutive_indices(remaining_nan)):
        print('Warning. Irreducible dataset. Deleting Pixels inside the image')
    global test 
    test = hyper_img
    hyper_img = np.delete(hyper_img, remaining_nan, axis=1)
    return hyper_img

def split_consecutive_indices(indices):
    result = []
    current_list = [indices[0]]
    for i in range(1, len(indices)):
        if indices[i] == indices[i-1] + 1:
            current_list.append(indices[i])
        else:
            result.append(current_list)
            current_list = [indices[i]]
    result.append(current_list)
    return result

#%%
if __name__ == '__main__':
    if 1:
        overlap_row = 84
        overlap_col = 84
        x = np.linspace(0, 2, 2)
        
        X = np.meshgrid(x,x)[0]
        
        X[0,1] = 0          # this shows x is the second index...
        plt.title('X is second index')
        plt.imshow(X)
        plt.show()
        
        
        data_path = r"/Users/mkunisch/Nextcloud/Manuel_BA/Stitching_Daten_Leber/pos2_largeFOV"
        data, lookup_x, lookup_y = stitch_load(data_path)
        stitch_y = stitch(data, lookup_x, lookup_y, overlap_row, overlap_col, scan_direction_y='up')
        plt.imshow(stitch_y[:,:,0], vmin=0, vmax=3000)
        stitch_y = np.moveaxis(stitch_y, -1, 0)
        stitch_y=stitch_y.astype('uint16')
    else:
        img = np.genfromtxt('z3D.txt')
        plt.imshow(img, vmin=0, vmax=1000)
        plt.show()
        hyper_im = remove_nan_edges(img)[:,:,0]
        plt.imshow(hyper_im, vmin=0, vmax=1000)
        plt.show()
        plt.imshow(test[:,:,0], vmin=0, vmax=1000)
        plt.show()
