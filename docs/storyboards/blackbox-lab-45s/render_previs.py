#!/usr/bin/env python3
"""Zero-cost synthetic storyboard previs for FactoryOS Film Studio, GH #434.

The result is an ANIMATIC, not real generated video, actor footage or an AI Film Studio production artifact.
Original procedural visuals and original synthesised ambience; no source photos, remote calls or paid media.
Requires Pillow, numpy and system ffmpeg/ffprobe. 7 shots, exactly 45s, 24fps, 960x540 H.264/AAC.
"""
import argparse, json, math, subprocess, wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

ROOT=Path(__file__).resolve().parent
W,H=1280,720
COLOR=(8,18,32);CYAN=(67,218,230);WARM=(247,181,107)
FONT_PATH='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD_PATH='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

def font(size,bold=False):
    return ImageFont.truetype(BOLD_PATH if bold else FONT_PATH,size)

def line(d, xy, c=CYAN, width=2):d.line(xy,fill=c,width=width)

def base(i):
    # Small original cinematic gradient + grain, reproducible.
    yy=np.linspace(0,1,H)[:,None,None]
    xx=np.linspace(0,1,W)[None,:,None]
    ground=np.array([6,13,24])[None,None,:]+(yy*np.array([7,12,20])[None,None,:]).astype(float)
    ground=np.broadcast_to(ground,(H,W,3)).copy()
    v=np.exp(-((xx-(.12+i*.13))**2)/(.11**2))*.27
    ground+=v*np.array([9,60,82])[None,None,:]
    ground+=np.exp(-((xx-.76)**2)/(.25**2))*.07*np.array([98,26,12])[None,None,:]
    grain=np.random.default_rng(1100+i).normal(0,1.7,(H,W,1))
    ground=np.uint8(np.clip(ground+grain,0,255))
    return Image.fromarray(ground,'RGB')

def rectangle(d,box,fill=None,outline=None,width=2,radius=0):
    d.rounded_rectangle(box,radius=radius,fill=fill,outline=outline,width=width)

def glow(img, x,y,r,color, strength=2):
    lay=Image.new('RGBA',(W,H),(0,0,0,0));d=ImageDraw.Draw(lay)
    d.ellipse((x-r,y-r,x+r,y+r),fill=(*color,100))
    lay=lay.filter(ImageFilter.GaussianBlur(r/2))
    for _ in range(strength):img=Image.alpha_composite(img.convert('RGBA'),lay)
    return img.convert('RGB')

def city(img,d):
    rng=np.random.default_rng(76)
    for n,x in enumerate(range(0,W,72)):
        ht=int(rng.integers(140,420)); yy=H-105-ht
        d.rectangle([x,yy,x+70,H],fill=(8+int(n%3)*3,22+int(n%4)*2,36))
        for wy in range(yy+17,H-120,20):
            for wx in range(x+12,x+64,17):
                if rng.random()<.24:d.rectangle([wx,wy,wx+6,wy+9],fill=(111,131,148) if rng.random()<.5 else WARM)
    d.polygon([(0,H-100),(W,H-100),(W,H),(0,H)],fill=(6,16,24))
    for a in range(30):
        px=int(rng.integers(0,W));line(d,(px,H-94,px-20,H),c=(20,59,65),width=1)

def office(img,d):
    for k in range(7):
        x=100+k*175; polygon=[(x,140),(x+160,140),(x+160,652),(x,652)]
        d.polygon(polygon,fill=(9,28,44),outline=(24,74,98),width=2)
        for yy in range(174,626,70):
            for xx in range(x+20,x+150,58):
                d.rectangle([xx,yy,xx+37,yy+38],fill=(43,77,83) if (k+yy//70+xx//58)%5 else (173,112,67))
    d.polygon([(190,650),(1040,650),(800,720),(400,720)],fill=(14,33,42))

def research(img,d):
    for k in range(4):
        x,y=145+k*250,174+(k%2)*85
        rectangle(d,(x,y,x+285,y+310),fill=(11,31,47),outline=(34,130,157),width=2,radius=16)
        d.text((x+22,y+20),'SOURCE / '+str(k+1),font=font(19,True),fill=CYAN)
        for j in range(7):
            yy=y+78+j*28
            line(d,(x+28,yy,x+235-int((j+k)%3)*36,yy),c=(55,89,107),width=4)
        d.ellipse([x+226,y+239,x+254,y+267],outline=WARM,width=3)
    line(d,(0,605,W,605),c=(33,66,76),width=2)

def prototype(img,d):
    rectangle(d,(195,118,1070,515),fill=(5,16,27),outline=(57,140,163),width=5,radius=18)
    rectangle(d,(225,155,1040,486),fill=(7,25,41),outline=None,radius=7)
    for j in range(16):
        y=187+j*17;x=265+int(8*math.sin(j*2))
        length=150+(j*57)%560
        line(d,(x,y,x+length,y),c=CYAN if j%5==0 else (47,96,113),width=3)
    d.polygon([(155,525),(1100,525),(1170,605),(95,605)],fill=(27,53,64),outline=(68,115,125))
    for j in range(9):
        for k in range(20):
            if (j+k)%6:d.rectangle((160+k*46,535+j*7,192+k*46,538+j*7),fill=(18,34,41))

def media(img,d):
    # An abstract edit monitor, not a screenshot of real FactoryOS UI.
    rectangle(d,(150,110,1130,555),fill=(7,25,37),outline=(37,150,169),width=3,radius=16)
    d.text((190,145),'FILM STUDIO / PREVIS',font=font(27,True),fill=CYAN)
    for k in range(5):
        x=195+k*176
        d.rectangle((x,220,x+152,362),fill=(19+k*3,56+k*2,72+k*2),outline=(56,119,134),width=2)
        d.polygon([(x+45,244),(x+105,289),(x+45,335)],fill=(122,189,185))
    for k in range(15):
        x=194+k*58;d.rectangle((x,430,x+45,482),fill=CYAN if k%6<2 else (37,68,87))
    d.line((194,506,1046,506),fill=WARM,width=4)
    d.ellipse((680,489,712,521),fill=WARM)

def approval(img,d):
    rectangle(d,(250,100,1040,602),fill=(9,27,42),outline=(37,111,135),width=3,radius=22)
    d.text((310,155),'PRIVATE PREVIEW',font=font(30,True),fill=CYAN)
    d.rectangle((310,230,980,420),fill=(13,41,58),outline=(70,122,147),width=2)
    for x in range(380,930,75):
        d.line((x,275,x-22,369),fill=(29,72,96),width=3)
    rectangle(d,(310,476,602,550),fill=(44,82,88),outline=CYAN,width=2,radius=12)
    rectangle(d,(645,476,980,550),fill=(63,104,86),outline=(105,220,170),width=2,radius=12)
    d.text((360,491),'REVIEW',font=font(30,True),fill=(235,242,248))
    d.text((699,491),'APPROVE',font=font(30,True),fill=(233,246,240))

def brand(img,d):
    for k in range(17):
        r=45+k*24; c=(11+int(1.1*k),37+int(2*k),57+int(2*k))
        d.ellipse((W//2-r,H//2-r,W//2+r,H//2+r),outline=c,width=2)
    for i in range(11):
        ang=i*2*math.pi/11
        x=W/2+300*math.cos(ang);y=H/2+230*math.sin(ang)
        line(d,(W/2,H/2,x,y),c=(24,81,100),width=2)
        d.ellipse((x-7,y-7,x+7,y+7),fill=CYAN if i%2 else WARM)

DRAW=[city,office,research,prototype,media,approval,brand]
TITLES=["ИДЕЯ", "ГИПОТЕЗА", "ДОКАЗАТЕЛЬСТВА", "ПРОТОТИП", "КРЕАТИВ", "ПРОВЕРКА", "BLACKBOX LAB"]
SUB=["ОТ ВОПРОСА К ЭКСПЕРИМЕНТУ","ИССЛЕДОВАНИЕ И ДЕБАТЫ","ФАКТЫ ВМЕСТО ДОГАДОК","ОТ ПЛАНА К РЕАЛЬНОЙ СБОРКЕ","СЦЕНАРИЙ, ВИЗУАЛЫ, МОНТАЖ","ЧЕЛОВЕК ПРИНИМАЕТ РЕШЕНИЕ","FACTORYOS  /  THE EXPERIMENT BEGINS"]

def frame_image(i,path):
    im=base(i);d=ImageDraw.Draw(im)
    DRAW[i](im,d)
    # Contrast-controlled graphic composition.
    rect=Image.new('RGBA',(W,H),(0,0,0,0));rd=ImageDraw.Draw(rect)
    rd.rectangle((0,0,W,108),fill=(2,10,19,150))
    rd.rectangle((0,572,W,H),fill=(2,10,19,200))
    rd.rectangle((0,0,15,H),fill=(40,184,204,255))
    im=Image.alpha_composite(im.convert('RGBA'),rect)
    d=ImageDraw.Draw(im)
    d.text((60,40),'BLACKBOX LAB  //  FACTORYOS',font=font(21,True),fill=CYAN)
    d.text((60,575),TITLES[i],font=font(51,True),fill=(236,249,255),stroke_width=1,stroke_fill=(11,16,24))
    d.text((64,640),SUB[i],font=font(21),fill=(188,214,224))
    d.text((1074,645),'DEMO  /  PREVIS',font=font(14,True),fill=WARM)
    # A thin film timeline implies shot segmentation without fake app telemetry.
    for j in range(7):
        d.rectangle((64+j*60,693,117+j*60,696),fill=CYAN if j<=i else (30,64,77))
    im.convert('RGB').save(path,quality=94)

def ambient_wave(path,secs=45,rate=24000):
    # Entirely original ambient audio; not voiceover and not copyrighted stock music.
    t=np.arange(secs*rate,dtype=np.float64)/rate
    fade=np.minimum(1,np.minimum(t/2,(secs-t)/3))
    layer=(np.sin(2*np.pi*82.4*t)+.5*np.sin(2*np.pi*123.47*t+.2*np.sin(2*np.pi*.25*t))+.36*np.sin(2*np.pi*164.8*t))
    swell=.55+.28*np.sin(2*np.pi*.08*t)
    sample=.075*fade*layer*swell
    for start in [0,5,11,17,24,30,36]:
        starti=int(start*rate);n=min(int(rate*.35),len(sample)-starti)
        if n>0:
            tt=np.arange(n)/rate
            sample[starti:starti+n]+=.018*np.sin(2*np.pi*440*tt)*np.exp(-tt*14)
    pcm=(np.clip(sample,-.8,.8)*32767).astype('<i2')
    with wave.open(str(path),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(pcm.tobytes())

def run(cmd):
    subprocess.run(cmd,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--storyboard',default=str(ROOT/'storyboard.json'));p.add_argument('--output',default=str(ROOT/'blackbox_lab_previs.mp4'));args=p.parse_args()
    story=json.loads(Path(args.storyboard).read_text(encoding='utf-8'))
    shots=story['shots'];assert len(shots)==7 and sum(int(s['duration_sec']) for s in shots)==45
    assert all(shots[i]['start_sec']==sum(int(s['duration_sec']) for s in shots[:i]) for i in range(7))
    out=Path(args.output).resolve();work=out.parent/'previs_work';work.mkdir(parents=True,exist_ok=True)
    files=[]
    for i,shot in enumerate(shots):
        png=work/f'{i+1:02d}.png';mp4=work/f'{i+1:02d}.mp4'
        frame_image(i,png)
        frames=int(shot['duration_sec']*24)
        run(['ffmpeg','-y','-hide_banner','-loglevel','error','-loop','1','-framerate','24','-i',str(png),
             '-vf',f"zoompan=z='min(zoom+0.00018,1.06)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=960x540:fps=24,format=yuv420p",
             '-frames:v',str(frames),'-c:v','libx264','-preset','ultrafast','-crf','24',str(mp4)])
        files.append(mp4)
    concat=work/'shots.txt';concat.write_text(''.join("file '"+str(f)+"'\n" for f in files))
    silent=work/'silent.mp4';run(['ffmpeg','-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',str(concat),'-c','copy',str(silent)])
    audio=work/'original_ambient.wav';ambient_wave(audio)
    run(['ffmpeg','-y','-hide_banner','-loglevel','error','-i',str(silent),'-i',str(audio),'-c:v','copy','-c:a','aac','-b:a','128k','-shortest','-movflags','+faststart',str(out)])
    proof=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,codec_name,width,height,r_frame_rate','-of','json',str(out)],text=True))
    assert abs(float(proof['format']['duration'])-45)<.12,proof
    run(['ffmpeg','-hide_banner','-loglevel','error','-i',str(out),'-f','null','-'])
    (out.parent/'previs_qa.json').write_text(json.dumps({'artifact':out.name,'notice':'SYNTHETIC ANIMATIC ONLY; no real/stock frames, no natural voice, not AI film generator proof','decode':'pass','ffprobe':proof},indent=2))
    print('PREVIS PASS:',out,proof)

if __name__=='__main__':main()
