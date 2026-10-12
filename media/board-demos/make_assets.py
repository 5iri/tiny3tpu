"""Build README diagrams from saved measurements. No board connection needed.

Requires Pillow. Source GIFs and physical footage are kept unchanged.
"""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BG = '#101820'
FG = '#f3f5f2'
MUTED = '#b5c3c9'
TEAL = '#4ed9c1'
GOLD = '#ffcc65'

def font(size, bold=False):
    names = (['/System/Library/Fonts/Supplemental/Arial Bold.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'] if bold else
             ['/System/Library/Fonts/Supplemental/Arial.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'])
    for name in names:
        if Path(name).exists(): return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)

def text(d, xy, value, size=24, color=FG, bold=False):
    d.text(xy, value, font=font(size, bold), fill=color)

def box(d, xy, title, subtitle, color=TEAL):
    x,y,w,h=xy
    d.rounded_rectangle((x,y,x+w,y+h), radius=12, fill='#20303a', outline=color, width=2)
    text(d,(x+18,y+20),title,25,color,True)
    text(d,(x+18,y+60),subtitle,20)

def arrow(d,x1,y1,x2,y2):
    d.line((x1,y1,x2,y2),fill=MUTED,width=3)
    d.polygon([(x2,y2),(x2-10,y2-6),(x2-10,y2+6)],fill=MUTED)

im=Image.new('RGB',(1200,700),BG);d=ImageDraw.Draw(im)
text(d,(40,30),'ONE SMALL TPU, THREE WAYS TO SEE IT WORK',32,FG,True)
text(d,(40,80),'The compiler runs on the development computer. The FPGA runs the program.',24,MUTED)
text(d,(40,139),'KC705 / DIRECT HDMI',19,TEAL,True)
for xy,title,sub in [((40,177,250,112),'JAX / StableHLO','Compile to RISC-V'),((330,177,360,112),'CPU + two 4x4 TPUs','Update state and transform mesh'),((730,177,425,112),'Renderer + framebuffer','Draw pixels and send HDMI')]:box(d,xy,title,sub)
arrow(d,292,233,324,233);arrow(d,692,233,724,233)
text(d,(40,327),'KC705 / UART DEMOS',19,TEAL,True)
box(d,(40,363,530,112),'CPU + two 4x4 TPUs','Compute banana, digits, attention or cloth')
box(d,(630,363,525,112),'Host viewer','Receive results over UART and draw pixels')
arrow(d,574,419,624,419)
text(d,(40,511),'CHROMATIC / HANDHELD',19,GOLD,True)
box(d,(40,547,530,112),'One 4x4 TPU + hardware controller','Transform the mesh; no CPU in this image',GOLD)
box(d,(630,547,525,112),'Renderer + framebuffer + LCD','All image generation stays on the handheld',GOLD)
arrow(d,574,603,624,603)
im.save(HERE/'architecture.png',optimize=True)

checks=json.loads((ROOT/'media/showcase/evidence/physical-check.json').read_text())['checks']
sw=checks[1]['compute_ms'];hw=checks[2]['compute_ms'];saved=100*(1-hw/sw)
im=Image.new('RGB',(1200,570),BG);d=ImageDraw.Draw(im)
text(d,(40,32),'ATTENTION ON THE PHYSICAL KC705',34,FG,True)
text(d,(40,91),'Same 8-token fixture. Same checked output. Less time computing exponential.',23,MUTED)
for y,label,value,color in [(182,'Software exponential',sw,'#7493a6'),(301,'Hardware CORDIC',hw,TEAL)]:
 text(d,(40,y-39),label,25)
 d.rectangle((40,y,40+int(value/60*950),y+53),fill=color)
 text(d,(55+int(value/60*950),y+8),f'{value:.2f} ms',25,color,True)
text(d,(40,407),f'{saved:.1f}% less compute time',34,TEAL,True)
text(d,(40,461),'All 64 checked output words matched the native generated-C reference.',23)
text(d,(40,510),'Measured board cycles at 100 MHz. Excludes UART and host drawing. Synthetic weights.',20,MUTED)
im.save(HERE/'attention-timing.png',optimize=True)

# A compact gallery made only from saved frames, with each image source identified.
im=Image.new('RGB',(1440,920),BG);d=ImageDraw.Draw(im)
text(d,(35,24),'TINY3TPU / RUNNING ON REAL HARDWARE',35,FG,True)
cards=[('hdmi-board.jpg','KC705 HDMI','Physical monitor footage'),
       ('banana-poster.png','UART banana','Pixels from board-returned geometry'),
       ('classifier-poster.png','MNIST classifier','Physical board predictions'),
       ('cloth-poster.png','Cloth physics','Physical board state; replay is sped up')]
for i,(name,title,sub) in enumerate(cards):
 x=30+i*355
 frame=Image.open(HERE/name).convert('RGB');frame.thumbnail((330,705))
 im.paste(frame,(x+(330-frame.width)//2,110+(705-frame.height)//2))
 text(d,(x,824),title,25,TEAL,True)
 text(d,(x,864),sub,15,MUTED)
im.save(HERE/'gallery.jpg',quality=90,optimize=True)
print('Wrote architecture.png, attention-timing.png, gallery.jpg')
