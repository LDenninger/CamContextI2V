import os
import numpy as np
from tqdm import tqdm
from PIL import Image
from einops import rearrange
from pathlib import Path
import imageio
import logging
mainlogger = logging.getLogger('mainlogger')

import torch
import torchvision
from torch import Tensor
from torchvision.utils import make_grid
from torchvision.transforms.functional import to_tensor


def frames_to_mp4(frame_dir,output_path,fps):
    def read_first_n_frames(d: os.PathLike, num_frames: int):
        if num_frames:
            images = [Image.open(os.path.join(d, f)) for f in sorted(os.listdir(d))[:num_frames]]
        else:
            images = [Image.open(os.path.join(d, f)) for f in sorted(os.listdir(d))]
        images = [to_tensor(x) for x in images]
        return torch.stack(images)
    videos = read_first_n_frames(frame_dir, num_frames=None)
    videos = videos.mul(255).to(torch.uint8).permute(0, 2, 3, 1)
    torchvision.io.write_video(output_path, videos, fps=fps, video_codec='h264', options={'crf': '10'})


def tensor_to_mp4(video, savepath, fps, rescale=True, nrow=None):
    """
    video: torch.Tensor, b,c,t,h,w, 0-1
    if -1~1, enable rescale=True
    """
    n = video.shape[0]
    video = video.permute(2, 0, 1, 3, 4) # t,n,c,h,w
    nrow = int(np.sqrt(n)) if nrow is None else nrow
    frame_grids = [torchvision.utils.make_grid(framesheet, nrow=nrow, padding=0) for framesheet in video] # [3, grid_h, grid_w]
    grid = torch.stack(frame_grids, dim=0) # stack in temporal dim [T, 3, grid_h, grid_w]
    grid = torch.clamp(grid.float(), -1., 1.)
    if rescale:
        grid = (grid + 1.0) / 2.0
    grid = (grid * 255).to(torch.uint8).permute(0, 2, 3, 1) # [T, 3, grid_h, grid_w] -> [T, grid_h, grid_w, 3]
    torchvision.io.write_video(savepath, grid, fps=fps, video_codec='h264', options={'crf': '10'})

    
def tensor2videogrids(video, root, filename, fps, rescale=True, clamp=True):
    assert(video.dim() == 5) # b,c,t,h,w
    assert(isinstance(video, torch.Tensor))

    video = video.detach().cpu()
    if clamp:
        video = torch.clamp(video, -1., 1.)
    n = video.shape[0]
    video = video.permute(2, 0, 1, 3, 4) # t,n,c,h,w
    frame_grids = [torchvision.utils.make_grid(framesheet, nrow=int(np.sqrt(n))) for framesheet in video] # [3, grid_h, grid_w]
    grid = torch.stack(frame_grids, dim=0) # stack in temporal dim [T, 3, grid_h, grid_w]
    if rescale:
        grid = (grid + 1.0) / 2.0
    grid = (grid * 255).to(torch.uint8).permute(0, 2, 3, 1) # [T, 3, grid_h, grid_w] -> [T, grid_h, grid_w, 3]
    path = os.path.join(root, filename)
    torchvision.io.write_video(path, grid, fps=fps, video_codec='h264', options={'crf': '10'})

def log_evaluation(batch_logs,
                    save_dir, 
                    save_fps=10, 
                    save_as_gif = False, 
                    rescale = False, 
                    save_image_condition = False,
                    print_out=False):

    if batch_logs is None:
        return False

    
    if not 'samples' in batch_logs:
        mainlogger.warning("Trying to log evaluation batch without 'samples' present." )
    
    samples = batch_logs['samples']
    camera_data = None
    if "camera_data" in batch_logs:
        camera_data = batch_logs["camera_data"]
    ground_truth = batch_logs["gt_video"]
    cond_images = batch_logs["image_condition"].squeeze(2)
    captions = batch_logs["condition"]
    add_cond_images = None
    if "cond_frames" in batch_logs:
        add_cond_images = batch_logs["cond_frames"]
        #add_cond_images = rearrange(add_cond_images, 'B N C H W -> B N H W C')

    #cond_images = rearrange(cond_images, 'B C H W -> B H W C')
    samples = rearrange(samples, 'B C T H W -> B T H W C')
    ground_truth = rearrange(ground_truth, 'B C T H W -> B T H W C')

    if rescale:
        samples = (samples + 1.0) / 2.0  # -1,1 -> 0,1
        ground_truth = (ground_truth + 1.0) / 2.0  # -1,1 -> 0,1
        cond_images = (cond_images + 1.0) / 2.0  # -1,1 -> 0,1
        if add_cond_images is not None:
            add_cond_images = (add_cond_images + 1.0) / 2.0  # -1,1 -> 0,1

    samples = (samples * 255).clamp(0, 255).to(torch.uint8)
    ground_truth = (ground_truth * 255).clamp(0, 255).to(torch.uint8)
    cond_images = (cond_images * 255).clamp(0, 255).to(torch.uint8)
    if add_cond_images is not None:
        add_cond_images = (add_cond_images * 255).clamp(0, 255).to(torch.uint8)

    video_names = [str(Path(vp).stem) for vp in batch_logs['video_path']]
    batch_size = samples.shape[0]
    
    for i in range(batch_size):
        if not os.path.exists(Path(save_dir) / video_names[i]):
            os.makedirs(Path(save_dir) / video_names[i])

        file_name = Path(save_dir) / video_names[i] / (f"generated.gif" if save_as_gif else f"generated.mp4")
        gt_file_name = Path(save_dir) / video_names[i] / (f"ground_truth.gif" if save_as_gif else f"ground_truth.mp4")
        cam_data_file_name = Path(save_dir) / video_names[i] / "camera_data.npy"
        caption_file_name = Path(save_dir) / video_names[i] / "captions.txt"
        sample = samples[i]

        gt_video = ground_truth[i]
        try:
            if save_as_gif:
                sample = sample.numpy()
                gt_video = gt_video.numpy()
                imageio.mimsave(file_name, sample, fps=save_fps)
                imageio.mimsave(gt_file_name, gt_video, fps=save_fps)
            else:
                torchvision.io.write_video(file_name, sample, fps=save_fps, video_codec='h264', options={'crf': '10'})
                torchvision.io.write_video(gt_file_name, gt_video, fps=save_fps, video_codec='h264', options={'crf': '10'})
        except Exception as e:
            mainlogger.warning(f"Failed to save results for {video_names[i]}: {e}")

        if add_cond_images is not None:
            imgs_cond = add_cond_images[i]
            for j in range(imgs_cond.shape[0]):
                img_cond = imgs_cond[j]
                torchvision.io.write_png(img_cond, Path(save_dir) / video_names[i] / f"context_{j}.png")
        if camera_data is not None:
            cdata = camera_data[i]
            np.save(cam_data_file_name, cdata)

        with open(caption_file_name, 'w') as f:
            for j, txt in enumerate(captions):
                f.write(f'{txt}\n')
            f.close()

        if save_image_condition:
            cond_image = cond_images[i]
            torchvision.io.write_png(cond_image, Path(save_dir) / video_names[i] / "condition.png")                

        if print_out:
            mainlogger.info(f"Saved evaluation results for: {video_names[i]}")

    return True
    

    
def log_local(batch_logs, save_dir, save_fps=10, rescale=True):
    if batch_logs is None:
        return None
    """ save images and videos from images dict """
    def save_img_grid(grid, path, rescale):
        if rescale:
                grid = (grid + 1.0) / 2.0  # -1,1 -> 0,1; c,h,w
        grid = grid.transpose(0, 1).transpose(1, 2).squeeze(-1)
        grid = grid.numpy()
        grid = (grid * 255).astype(np.uint8)
        os.makedirs(os.path.split(path)[0], exist_ok=True)
        Image.fromarray(grid).save(path)

    for key in batch_logs:
        
        value = batch_logs[key]
        if key == "camera_data":
            path = os.path.join(save_dir, f"{key}.txt")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            assert value.size(0) == 1, f"batch size {value.size(0)} is not 1"
            np.savetxt(path, value[0, :, 1:])
        elif key == "cond_frame_scale":
            path = os.path.join(save_dir, f"{key}.txt")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            assert value.size(0) == 1, f"batch size {value.size(0)} is not 1"
            np.savetxt(path, value)
        elif isinstance(value, list) and isinstance(value[0], str):
            ## a batch of captions
            path = os.path.join(save_dir, f"{key}.txt")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w') as f:
                for i, txt in enumerate(value):
                    f.write(f'idx={i}, txt={txt}\n')
                f.close()
        elif isinstance(value, torch.Tensor) and (value.dim() == 5 and value.shape[2] != 1):
            value = value.squeeze(2) if value.dim() == 6 else value
            ## save video grids
            video = value # b,c,t,h,w
            ## only save grayscale or rgb mode
            if video.shape[1] != 1 and video.shape[1] != 3:
                continue
            n = video.shape[0]
            video = video.permute(2, 0, 1, 3, 4) # t,n,c,h,w
            frame_grids = [torchvision.utils.make_grid(framesheet, nrow=int(1), padding=0) for framesheet in video] #[3, n*h, 1*w]
            grid = torch.stack(frame_grids, dim=0) # stack in temporal dim [t, 3, n*h, w]
            if rescale:
                grid = (grid + 1.0) / 2.0
            grid = (grid * 255).clamp(0, 255).to(torch.uint8).permute(0, 2, 3, 1)
            path = os.path.join(save_dir, f"{key}.mp4")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            torchvision.io.write_video(path, grid, fps=save_fps, video_codec='h264', options={'crf': '10'})
            
            ## save frame sheet
            img = value
            video_frames = rearrange(img, 'b c t h w -> (b t) c h w')
            t = img.shape[2]
            grid = torchvision.utils.make_grid(video_frames, nrow=t, padding=0)
            path = os.path.join(save_dir, f"{key}.jpg")
            #save_img_grid(grid, path, rescale)
        elif isinstance(value, torch.Tensor) and (value.dim() == 4 or (value.dim() == 5 and value.shape[2] == 1)):
            ## save image grids
            value = value.squeeze(2) if value.dim() == 5 else value
            img = value
            ## only save grayscale or rgb mode
            if img.shape[1] != 1 and img.shape[1] != 3:
                continue
            n = img.shape[0]
            grid = torchvision.utils.make_grid(img, nrow=1, padding=0)
            path = os.path.join(save_dir, f"{key}.jpg")
            save_img_grid(grid, path, rescale)
        else:
            pass


def prepare_to_log(batch_logs, max_images=100000, clamp=True):
    if batch_logs is None:
        return None
    max_images = max_images if max_images > 0 else 100000
    # process
    for key in batch_logs:
        N = batch_logs[key].shape[0] if hasattr(batch_logs[key], 'shape') else len(batch_logs[key])
        N = min(N, max_images)
        batch_logs[key] = batch_logs[key][:N]
        ## in batch_logs: images <batched tensor> & caption <text list>
        if isinstance(batch_logs[key], torch.Tensor):
            batch_logs[key] = batch_logs[key].detach().cpu()
            # if key != "camera_data" and clamp:
            #     try:
            #         batch_logs[key] = torch.clamp(batch_logs[key].float(), -1., 1.)
            #     except RuntimeError:
            #         print("clamp_scalar_cpu not implemented for Half")
    return batch_logs

# ----------------------------------------------------------------------------------------------

def fill_with_black_squares(video, desired_len: int) -> Tensor:
    if len(video) >= desired_len:
        return video

    return torch.cat([
        video,
        torch.zeros_like(video[0]).unsqueeze(0).repeat(desired_len - len(video), 1, 1, 1),
    ], dim=0)

# ----------------------------------------------------------------------------------------------
def load_num_videos(data_path, num_videos):
    # first argument can be either data_path of np array 
    if isinstance(data_path, str):
        videos = np.load(data_path)['arr_0'] # NTHWC
    elif isinstance(data_path, np.ndarray):
        videos = data_path
    else:
        raise Exception

    if num_videos is not None:
        videos = videos[:num_videos, :, :, :, :]
    return videos

def npz_to_video_grid(data_path, out_path, num_frames, fps, num_videos=None, nrow=None, verbose=True):
    # videos = torch.tensor(np.load(data_path)['arr_0']).permute(0,1,4,2,3).div_(255).mul_(2) - 1.0 # NTHWC->NTCHW, np int -> torch tensor 0-1
    if isinstance(data_path, str):
        videos = load_num_videos(data_path, num_videos)
    elif isinstance(data_path, np.ndarray):
        videos = data_path
    else:
        raise Exception
    n,t,h,w,c = videos.shape
    videos_th = []
    for i in range(n):
        video = videos[i, :,:,:,:]
        images = [video[j, :,:,:] for j in range(t)]
        images = [to_tensor(img) for img in images]
        video = torch.stack(images)
        videos_th.append(video)
    if verbose:
        videos = [fill_with_black_squares(v, num_frames) for v in tqdm(videos_th, desc='Adding empty frames')] # NTCHW
    else:
        videos = [fill_with_black_squares(v, num_frames) for v in videos_th] # NTCHW

    frame_grids = torch.stack(videos).permute(1, 0, 2, 3, 4) # [T, N, C, H, W]
    if nrow is None:
        nrow = int(np.ceil(np.sqrt(n)))
    if verbose:
        frame_grids = [make_grid(fs, nrow=nrow) for fs in tqdm(frame_grids, desc='Making grids')]
    else:
        frame_grids = [make_grid(fs, nrow=nrow) for fs in frame_grids]

    if os.path.dirname(out_path) != "":
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
    frame_grids = (torch.stack(frame_grids) * 255).to(torch.uint8).permute(0, 2, 3, 1) # [T, H, W, C]
    torchvision.io.write_video(out_path, frame_grids, fps=fps, video_codec='h264', options={'crf': '10'})
