"""Read the original SGI terrain tile stream, without modifying game assets."""
from pathlib import Path
from functools import lru_cache
import os
import threading
from PIL import Image

MBM_SIZE = (9744, 4872)
MIP_STEPS = (8, 16)
_SHARED = None
_SHARED_LOCK = threading.Lock()
_WARM_STARTED = False


def world_pixel(x,y):
    return 48+96*x+48*(y%2),24+24*y


def mip_factor(src_w, dest_w):
    """Pick a downsample so a wide MBM crop is not stitched from 40k tiles."""
    src_w = max(1, int(src_w))
    dest_w = max(1, int(dest_w))
    if src_w <= max(dest_w * 1.6, 900):
        return 1
    for factor in MIP_STEPS:
        if src_w / factor <= dest_w * 2.2:
            return factor
    return MIP_STEPS[-1]


def blit_mip_box(mip, factor, box, dest_w, dest_h, fill='#68724e'):
    """Draw a mip so source `box` maps onto the destination.

    Off-map padding stays in the frame. Stretching only the in-map pixels
    to the full window shifts vision south of the city sprites once the
    zoomed-out crop is taller than SanInet.mbm.
    """
    left, top, right, bottom = map(int, box)
    dest_w = max(1, int(dest_w))
    dest_h = max(1, int(dest_h))
    box_w = max(1, right - left)
    box_h = max(1, bottom - top)
    out = Image.new('RGB', (dest_w, dest_h), fill)
    if mip is None or factor < 1:
        return out
    factor = int(factor)
    src_l = max(0, left // factor)
    src_t = max(0, top // factor)
    src_r = min(mip.width, (right + factor - 1) // factor)
    src_b = min(mip.height, (bottom + factor - 1) // factor)
    if src_r <= src_l or src_b <= src_t:
        return out
    piece = mip.crop((src_l, src_t, src_r, src_b))
    cover_l = src_l * factor
    cover_t = src_t * factor
    cover_r = src_r * factor
    cover_b = src_b * factor
    sx0 = (cover_l - left) * dest_w / box_w
    sy0 = (cover_t - top) * dest_h / box_h
    sx1 = (cover_r - left) * dest_w / box_w
    sy1 = (cover_b - top) * dest_h / box_h
    span_x = sx1 - sx0
    span_y = sy1 - sy0
    if span_x < 0.5 or span_y < 0.5:
        return out
    tw = max(1, int(round(span_x)))
    th = max(1, int(round(span_y)))
    scaled = piece.resize((tw, th), Image.Resampling.NEAREST)
    ox = int(round(sx0))
    oy = int(round(sy0))
    cut_l = max(0, -ox)
    cut_t = max(0, -oy)
    cut_r = min(tw, dest_w - ox)
    cut_b = min(th, dest_h - oy)
    if cut_r <= cut_l or cut_b <= cut_t:
        return out
    if cut_l or cut_t or cut_r != tw or cut_b != th:
        scaled = scaled.crop((cut_l, cut_t, cut_r, cut_b))
        ox += cut_l
        oy += cut_t
    out.paste(scaled, (ox, oy))
    return out


class Terrain:
    def __init__(self,path=None,size=None):
        explicit=Path(path) if path else None
        if explicit is not None:
            candidates=[explicit]
        else:
            candidates=[]
            if os.environ.get('SGI_TERRAIN_FILE'):candidates.append(Path(os.environ['SGI_TERRAIN_FILE']))
            candidates += [Path(__file__).parent/'assets'/'SanInet.mbm',Path('D:/Coding/sanguo-internet/run-3.5/3I/SanInet.mbm'),Path.home()/'Library/Application Support/CrossOver/Bottles/SanguoInternet/drive_c/sgi/run-3.5/3I/SanInet.mbm',Path.home()/'Library/Application Support/SGI-Wine/prefix-sikarugir10/drive_c/sgi/run-3.5/3I/SanInet.mbm']
        self.path=next((p for p in candidates if p.is_file()),None)
        if self.path is None:raise FileNotFoundError('未找到地图像素 '+ (path or 'SanInet.mbm'))
        expected=tuple(size) if size else MBM_SIZE
        raw=self.path.read_bytes()
        with Image.open(self.path) as im:
            if im.size!=expected or im.mode!='P':raise ValueError('地图规格不匹配，不能使用本坐标配准')
            self.palette=im.getpalette()
            self.size=im.size
        self.tiles_x=self.size[0]//48
        self.tiles_y=self.size[1]//24
        offset=int.from_bytes(raw[10:14],'little');self.data=raw[offset:]
        if len(self.data)<self.tiles_x*self.tiles_y*1152:raise ValueError('地图像素不完整')
        self._mips={}
        self._mip_lock=threading.Lock()
    @lru_cache(maxsize=512)
    def tile(self,x,y):
        offset=(y*self.tiles_x+x)*1152
        tile=Image.frombytes('P',(48,24),self.data[offset:offset+1152]).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        tile.putpalette(self.palette)
        return tile.convert('RGB')
    def crop(self,box):
        left,top,right,bottom=map(int,box)
        out=Image.new('RGB',(right-left,bottom-top),'#68724e')
        for y in range(max(0,top//24),min(self.tiles_y,(bottom+23)//24)):
            for x in range(max(0,left//48),min(self.tiles_x,(right+47)//48)):
                out.paste(self.tile(x,y),(x*48-left,y*24-top))
        return out
    def mip(self,factor):
        factor=int(factor)
        if factor<=1:
            return None
        cached=self._mips.get(factor)
        if cached is not None:
            return cached
        with self._mip_lock:
            cached=self._mips.get(factor)
            if cached is not None:
                return cached
            return self._build_mip(factor)

    def _build_mip(self,factor):
        width,height=self.size[0]//factor,self.size[1]//factor
        lut=bytes((self.palette or [])[:768])
        if len(lut)<768:
            lut=lut+bytes(768-len(lut))
        out=bytearray(width*height*3)
        data=self.data
        for dy in range(height):
            sy=dy*factor
            tile_row=(sy//24)*self.tiles_x
            flipped=23-(sy%24)
            row=dy*width
            for dx in range(width):
                sx=dx*factor
                index=data[(tile_row+sx//48)*1152+flipped*48+(sx%48)]
                src=index*3
                dst=(row+dx)*3
                out[dst]=lut[src]
                out[dst+1]=lut[src+1]
                out[dst+2]=lut[src+2]
        image=Image.frombytes('RGB',(width,height),bytes(out))
        self._mips[factor]=image
        return image
    def crop_to(self,box,dest_w,dest_h):
        dest_w=max(1,int(dest_w));dest_h=max(1,int(dest_h))
        left,top,right,bottom=map(int,box)
        src_w=max(1,right-left)
        factor=mip_factor(src_w,dest_w)
        if factor==1:
            return self.crop(box).resize((dest_w,dest_h),Image.Resampling.NEAREST)
        return blit_mip_box(self.mip(factor),factor,(left,top,right,bottom),dest_w,dest_h)


def shared_terrain(warmup=False):
    """One MBM decode + mip cache for 全景 and 偷袭主城."""
    global _SHARED, _WARM_STARTED
    with _SHARED_LOCK:
        if _SHARED is None:
            _SHARED = Terrain()
        terrain = _SHARED
        start_warm = bool(warmup) and not _WARM_STARTED
        if start_warm:
            _WARM_STARTED = True
    if start_warm:
        def run():
            try:
                terrain.mip(8)
                terrain.mip(16)
            except Exception:
                pass
        threading.Thread(target=run, daemon=True, name='sgi-mbm-mip').start()
    return terrain
