"""Render the editable SVG into macOS ICNS. Build-only: Node/sharp and Pillow."""
from pathlib import Path
import io,struct
import subprocess
from PIL import Image
root=Path(__file__).parent/'assets'
subprocess.run(['node','-e',"require('sharp')(process.argv[1]).resize(1024,1024).png().toFile(process.argv[2]).catch(e=>{console.error(e);process.exit(1)})",str(root/'icon.svg'),str(root/'icon.png')],check=True)
png=(root/'icon.png').read_bytes()
im=Image.open(io.BytesIO(png)).convert('RGBA')
chunks=[]
for tag,size in [(b'icp4',16),(b'icp5',32),(b'icp6',64),(b'ic07',128),(b'ic08',256),(b'ic09',512),(b'ic10',1024)]:
    out=io.BytesIO();im.resize((size,size),Image.Resampling.LANCZOS).save(out,format='PNG')
    data=out.getvalue();chunks.append(tag+struct.pack('>I',len(data)+8)+data)
body=b''.join(chunks)
(root/'MediathekAtlas.icns').write_bytes(b'icns'+struct.pack('>I',len(body)+8)+body)
print('SVG, PNG and multi-resolution ICNS ready')
