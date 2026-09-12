"""Render the original, silent 24-second product workflow film.

Build-only dependencies: pip install Pillow imageio-ffmpeg
Usage: python scripts/render_demo_video.py --font /path/to/Arial.ttf
The committed MP4/poster/VTT need no video dependencies in production.
All visuals are drawn from code; no third-party footage is used.
"""
import argparse
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--font', default='/System/Library/Fonts/Supplemental/Arial.ttf')
args = parser.parse_args()
fonts = {size: ImageFont.truetype(args.font, size) for size in [11, 13, 14, 16, 18, 20, 22, 26, 30, 42, 52]}
W, H, FPS = 1280, 720, 24
GOLD, INK, MUTED = '#f5c451', '#f6edff', '#ad94c5'
base = Image.new('RGB', (W, H)); d = ImageDraw.Draw(base)
for y in range(H):
    strength = max(0, 1 - abs(y - 340) / 450)
    d.line([(0,y),(W,y)], fill=(int(16+9*strength),int(10+4*strength),int(26+16*strength)))
for x in range(0, W, 60): d.line([(x,0),(x,H)], fill='#231631')
for y in range(0, H, 60): d.line([(0,y),(W,y)], fill='#231631')

def text(draw, xy, value, size=16, color=INK): draw.text(xy, value, font=fonts[size], fill=color)
def rounded(draw, box, fill, outline='#5d4177', radius=15): draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=1)
def wrap(draw, value, width, size):
    lines, line = [], ''
    for word in value.split():
        candidate = (line + ' ' + word).strip()
        if draw.textlength(candidate, font=fonts[size]) > width and line: lines.append(line); line = word
        else: line = candidate
    return lines + ([line] if line else [])
def paragraph(draw, xy, value, width, size=20, color=INK, spacing=9):
    x,y = xy
    for line in wrap(draw,value,width,size): text(draw,(x,y),line,size,color); y += size+spacing

chapters = [
 ('01', 'Answer the moment.', 'A question is the start of an opportunity.', 'My AC stopped cooling. Can someone help tomorrow?', 'I can start a repair request. Is the system blowing warm air or not turning on?', 'INCOMING INQUIRY'),
 ('02', 'Ask the right question.', 'Give the conversation useful context.', 'It is running, but blowing warm air. I am in San Diego.', 'Thanks. What name should the team use, and what time works best for a follow-up?', 'UNDERSTANDING THE NEED'),
 ('03', 'Keep the details together.', 'One conversation. One clear request.', 'Alex Morgan. Tomorrow morning is best. Use my sample contact.', 'Sample request prepared: AC repair, San Diego, morning preferred.', 'SAMPLE LEAD PREPARED'),
 ('04', 'Make the next step clear.', 'Your team takes it from here.', 'Great. What happens next?', 'The service team would confirm availability and pricing. No real appointment is made in this demo.', 'READY FOR TEAM REVIEW'),
]

def frame(t):
    image = base.copy(); draw = ImageDraw.Draw(image); index = min(3,int(t//6)); c = chapters[index]
    text(draw,(65,62),'AI BUSINESS GURUS',14,GOLD); text(draw,(900,62),'WORKFLOW IN MOTION / SAMPLE',11,MUTED)
    text(draw,(64,109),c[1],52); text(draw,(66,174),c[2],20,MUTED)
    text(draw,(65,244),'THE CUSTOMER',11,MUTED); text(draw,(790,244),'YOUR AI ASSISTANT',11,MUTED)
    rounded(draw,(62,277,486,519),'#261634'); rounded(draw,(790,277,1217,519),'#24172f')
    text(draw,(86,301),'ALEX MORGAN',13,GOLD); paragraph(draw,(86,339),c[3],368,22)
    text(draw,(814,301),'SUMMIT HOME COMFORT',13,GOLD); paragraph(draw,(814,339),c[4],378,20)
    # Moving signal links and orbit paths explain the transfer of context.
    cy = 393
    for left,right in [(486,594),(686,790)]:
        draw.line([(left,cy),(right,cy)],fill='#654789',width=2)
        px = left + ((t*.34)%1)*(right-left)
        draw.ellipse((px-4,cy-4,px+4,cy+4),fill=GOLD)
    for n,r in enumerate([46,58,70]):
        draw.ellipse((640-r,cy-r*.66,640+r,cy+r*.66),outline=['#b385dd','#654084','#97713d'][n],width=1)
        angle = t*.65 + n*2
        px,py = 640+r*math.cos(angle),cy+r*.66*math.sin(angle)
        draw.ellipse((px-3,py-3,px+3,py+3),fill=GOLD if n==2 else '#c29af1')
    glow = int(5*math.sin(t*2))
    draw.ellipse((611-glow,364-glow,669+glow,422+glow),fill='#673799',outline='#b595df',width=2)
    text(draw,(627,375),'AI',26)
    text(draw,(543,489),c[5],11,GOLD)
    # Four real workflow stages, no invented performance statistics.
    labels=['01  ANSWER','02  QUALIFY','03  CAPTURE','04  HANDOFF']
    for i,label in enumerate(labels):
        x=64+i*302; color=GOLD if i==index else MUTED
        draw.line([(x,572),(x+263,572)],fill='#634973',width=2)
        if i <= index:
            progress = 1 if i<index else min(1,(t%6)/6)
            draw.line([(x,572),(x+263*progress,572)],fill=GOLD,width=3)
        text(draw,(x,589),label,13,color)
    text(draw,(65,647),'ILLUSTRATIVE WORKFLOW  /  FICTIONAL BUSINESS & CONTACT  /  NO REAL BOOKING',11,MUTED)
    text(draw,(1100,642),f'{min(24,int(t)):02d} / 24s',16,GOLD)
    return image

video = ROOT/'static/video/demo-workflow.mp4'; video.parent.mkdir(parents=True,exist_ok=True)
writer = imageio_ffmpeg.write_frames(str(video), (W,H), fps=FPS, codec='libx264', pix_fmt_in='rgb24', pix_fmt_out='yuv420p', quality=7, output_params=['-movflags','+faststart'], macro_block_size=16)
writer.send(None)
try:
    for i in range(FPS*24): writer.send(frame(i/FPS).tobytes())
finally: writer.close()
frame(2).save(ROOT/'static/img/demo-film-poster.png',optimize=True)
(ROOT/'static/video/demo-workflow.vtt').write_text('''WEBVTT

00:00.000 --> 00:06.000
Answer: A customer asks for AC repair. The assistant starts a request.

00:06.000 --> 00:12.000
Qualify: Understand the problem, location, and preferred timing.

00:12.000 --> 00:18.000
Capture: Gather the sample contact and service request together.

00:18.000 --> 00:24.000
Handoff: The team confirms availability and pricing. No real booking is made.
''')
print(f'Rendered {video} ({video.stat().st_size:,} bytes), poster and captions.')
