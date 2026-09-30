"""Rebuild publication cards from the saved board capture and measurements."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import json
ROOT=Path(__file__).resolve().parent
BG='#0b1220'; FG='#eef4fa'; MUT='#a0b0c5'; CYAN='#59e1df'; GOLD='#f4c76b'
def font(n,bold=False): return ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial'+(' Bold' if bold else '')+'.ttf',n)
def base(k,title,sub):
 im=Image.new('RGB',(1600,1000),BG); d=ImageDraw.Draw(im)
 d.text((80,52),'tiny3tpu   /   FIELD NOTES  '+k,font=font(24,True),fill=CYAN)
 d.text((80,118),title,font=font(66,True),fill=FG)
 d.text((80,205),sub,font=font(29),fill=MUT)
 d.line((80,905,1520,905),fill='#29364a',width=2)
 d.text((80,937),'KC705  /  Kintex-7  /  CPU + int8 TPU',font=font(23),fill=MUT)
 d.text((1160,937),'github.com/5iri/tiny3tpu',font=font(22),fill=CYAN)
 return im,d
def save(im,name): im.save(ROOT/name)
im,d=base('01','Physics stays on the board.','StableHLO is the compiler interface. JAX is an optional offline frontend.')
for x,label,lines,col in [(80,'01  EXPORT',['JAX or another','StableHLO producer'],CYAN),(580,'02  COMPILE',['Generic lowering','CPU / TPU placement'],GOLD),(1080,'03  EXECUTE',['VexRiscv + int8 TPU','State lives on KC705'],CYAN)]:
 d.rounded_rectangle((x,340,x+440,570),20,fill='#162236',outline=col,width=2)
 d.text((x+28,370),label,font=font(29,True),fill=col)
 for i,l in enumerate(lines): d.text((x+28,438+i*44),l,font=font(30),fill=FG)
for x in (530,1030): d.text((x,427),'→',font=font(40),fill=MUT)
d.text((80,660),'Board computes physics + camera transforms.',font=font(43,True),fill=FG)
d.text((80,728),'Host receives geometry and generates pixels.',font=font(36),fill=MUT)
d.text((80,826),'Cloth is one example. Compiler passes have no cloth-specific rules.',font=font(28),fill=CYAN)
save(im,'01-architecture.png')
m=json.loads((ROOT/'board-snapshot.json').read_text())
im,d=base('02','Cloth, on real FPGA hardware.','Actual live capture  /  VexRiscv at 100 MHz  /  TPU camera transforms')
pic=Image.open(ROOT/'board-capture.png').convert('RGB'); pic.thumbnail((900,570)); im.paste(pic,(80,290))
for y,v,l in [(315,f"{m['fps']:.1f} FPS",'Observed display rate'),(450,'28 vertices','Small cloth mesh'),(585,'264 words','State + camera checked'),(720,'0 host physics','CPU + TPU on board')]:
 d.text((1040,y),v,font=font(43,True),fill=CYAN); d.text((1040,y+60),l,font=font(26),fill=MUT)
d.text((80,860),'Display FPS is not real-time simulation speed. Each step advances 1/7680 s.',font=font(24),fill=MUT)
save(im,'02-live-board.png')
im,d=base('03','Moving data was the first bottleneck.','First cloth step  /  instrumented RTL at 100 MHz  /  lower is better')
for y,label,val,col in [(340,'Scalar transport + forced offload',350.81,MUT),(505,'Packed transport + forced offload',146.88,GOLD),(670,'Packed transport + costed placement',111.22,CYAN)]:
 d.text((80,y),label,font=font(31,True),fill=FG)
 d.rounded_rectangle((80,y+55,80+val/350.81*1130,y+113),8,fill=col)
 d.text((1260,y+55),f'{val:.2f} ms',font=font(32,True),fill=col)
d.text((80,835),'3.15× faster in this benchmark. Forcing int8 affine offload still lost to CPU placement.',font=font(26),fill=MUT)
save(im,'03-transport.png')
im,d=base('04','The next bottleneck: software float.','First-step RTL cycle attribution  /  current VexRiscv has no FPU')
vals=[('Multiply',47.88,CYAN),('Add',20.37,GOLD),('Divide',9.79,'#bda5ff'),('Subtract',7.15,'#ef97ab'),('Other',14.81,'#40536f')]
x=80
for label,v,col in vals:
 w=v/100*1440; d.rectangle((x,355,x+w,465),fill=col); x+=w
for i,(l,v,c) in enumerate(vals):
 y=520+i*52; d.rectangle((80,y+6,100,y+26),fill=c);d.text((122,y),f'{l}   {v:.2f}%',font=font(30),fill=FG)
d.text((700,550),'~85% of cycles',font=font(58,True),fill=CYAN)
d.text((700,640),'charged to float arithmetic',font=font(33),fill=FG)
d.text((700,720),'Next candidate: VexRiscv FPU + data cache.',font=font(27),fill=MUT)
d.text((80,855),'Attribution includes stalls; this is a profiling result, not a promised FPU speedup.',font=font(25),fill=MUT)
save(im,'04-bottleneck.png')
