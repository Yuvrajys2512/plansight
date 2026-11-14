from __future__ import annotations
import os
from pathlib import Path
from urllib.parse import urlparse

def _config():
    value = os.getenv("CLOUDINARY_URL", "")
    if not value:
        return None
    parsed = urlparse(value)
    return parsed.hostname, parsed.username, parsed.password

def upload_drawing(path: str | Path, public_id: str | None = None) -> str | None:
    cfg = _config()
    if not cfg:
        return None
    import cloudinary
    import cloudinary.uploader
    cloudinary.config(cloud_name=cfg[0], api_key=cfg[1], api_secret=cfg[2], secure=True)
    result = cloudinary.uploader.upload(str(path), public_id=public_id, resource_type="image", overwrite=True)
    return result["public_id"]

def transformed_url(public_id: str, transformation: str = "") -> str | None:
    cfg = _config()
    if not cfg:
        return None
    cloud_name = cfg[0]
    transform = f"{transformation}/" if transformation else ""
    return f"https://res.cloudinary.com/{cloud_name}/image/upload/{transform}{public_id}.jpg"

def evidence_crop_url(public_id: str, bbox: tuple[int,int,int,int], *, width: int, height: int, padding: int = 24) -> str | None:
    x0,y0,x1,y1=bbox
    x=max(0,x0-padding); y=max(0,y0-padding); w=min(width-x,x1-x0+2*padding); h=min(height-y,y1-y0+2*padding)
    return transformed_url(public_id, f"c_crop,g_north_west,w_{w},h_{h},x_{x},y_{y},f_auto,q_auto")

def highlight_url(public_id: str, bbox: tuple[int,int,int,int], *, width: int, height: int) -> str | None:
    # Cloudinary's generated RGB layer is positioned over the original drawing bounds.
    x0,y0,x1,y1=bbox
    return transformed_url(public_id, f"l_rgb:36D67E,w_{max(1,x1-x0)},h_{max(1,y1-y0)},o_35/fl_layer_apply,g_north_west,x_{max(0,x0)},y_{max(0,y0)}/f_auto,q_auto")
