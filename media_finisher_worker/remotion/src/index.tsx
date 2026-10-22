import React from 'react';
import {AbsoluteFill, Composition, Sequence, staticFile, useCurrentFrame, interpolate, OffthreadVideo, registerRoot} from 'remotion';

type Caption={start:number;end:number;text:string;keyword?:string};
type Motion={start:number;end:number;type:string;zoom:number};
type Graphic={start:number;end:number;text:string;type?:string;variant?:'kinetic_title'|'lower_third'|'callout'|'badge'};
type Props={
  videoPath:string; captions:Caption[]; motion:Motion[]; graphics:Graphic[];
  safeZones:{top?:number;bottom?:number;right?:number;left?:number};
  fps:number;durationInFrames:number;width:number;height:number;
};

const MediaFinish:React.FC<Props>=(p)=>{
  const frame=useCurrentFrame();
  const t=frame/p.fps;
  const active=p.motion.filter(m=>t>=m.start&&t<=m.end);
  let scale=1;
  for(const m of active){
    const local=(t-m.start)/Math.max(.01,m.end-m.start);
    const wave=local<.5?interpolate(local,[0,.5],[1,m.zoom]):interpolate(local,[.5,1],[m.zoom,1]);
    scale=Math.max(scale,wave);
  }
  const bottom=Math.max(.20,p.safeZones?.bottom??.20);
  const top=Math.max(.12,p.safeZones?.top??.12);
  return <AbsoluteFill style={{backgroundColor:'#000',overflow:'hidden'}}>
    <AbsoluteFill style={{transform:"scale("+scale+")"}}>
      <OffthreadVideo src={staticFile(p.videoPath)} style={{width:'100%',height:'100%',objectFit:'cover'}}/>
    </AbsoluteFill>
    {(p.captions||[]).map((c,i)=>{
      const from=Math.max(0,Math.floor(c.start*p.fps)),dur=Math.max(1,Math.ceil((c.end-c.start)*p.fps));
      const words=c.text.split(/\s+/);
      return <Sequence key={"c"+i} from={from} durationInFrames={dur}>
        <AbsoluteFill style={{justifyContent:'flex-end',alignItems:'center',paddingBottom:(bottom*100+4)+'%',pointerEvents:'none'}}>
          <div style={{maxWidth:'78%',backgroundColor:'rgba(0,0,0,.72)',borderRadius:18,padding:'14px 22px',fontFamily:'DejaVu Sans, sans-serif',fontWeight:800,fontSize:54,lineHeight:1.05,textAlign:'center',color:'white',textShadow:'0 2px 8px #000'}}>
            {words.map((w,j)=><span key={j} style={{color:c.keyword&&w.replace(/[^\w']/g,'').toLowerCase()===c.keyword.replace(/[^\w']/g,'').toLowerCase()?'#70e5ff':'white'}}>{w}{j<words.length-1?' ':''}</span>)}
          </div>
        </AbsoluteFill>
      </Sequence>
    })}
    {(p.graphics||[]).map((g,i)=>{
      const from=Math.max(0,Math.floor(g.start*p.fps)),dur=Math.max(1,Math.ceil((g.end-g.start)*p.fps));
      const local=Math.max(0,frame-from),edge=Math.max(1,Math.min(10,Math.floor(dur*.25)));
      const enter=Math.min(1,local/edge),exit=Math.min(1,Math.max(0,(dur-local)/edge)),visible=Math.min(enter,exit);
      const variants:Array<'kinetic_title'|'lower_third'|'callout'|'badge'>=['kinetic_title','lower_third','callout','badge'];
      const variant=g.variant||variants[i%variants.length];
      const slideY=(1-visible)*-42,pulse=.94+visible*.06+(Math.sin(local*.45)*.012*visible);
      const slideX=(1-visible)*(variant==='lower_third'?-120:variant==='callout'?110:0);
      const base:any={opacity:visible,fontFamily:'DejaVu Sans, sans-serif',fontWeight:900,color:'#eefcff',letterSpacing:.4,
        transform:"translate("+slideX+"px,"+slideY+"px) scale("+pulse+")",textShadow:'0 3px 15px rgba(0,0,0,.65)'};
      let wrap:any={justifyContent:'flex-start',alignItems:'flex-start',paddingTop:(top*100+4)+'%',paddingLeft:'7%',paddingRight:'14%',pointerEvents:'none'};
      let box:any={...base,backgroundColor:'rgba(5,18,28,.86)',border:'2px solid rgba(74,211,255,.72)',borderRadius:18,padding:'14px 20px',fontSize:42,boxShadow:'0 16px 42px rgba(0,0,0,.42)'};
      if(variant==='kinetic_title'){
        wrap={...wrap,justifyContent:'center',alignItems:'center',paddingTop:0,paddingLeft:'8%',paddingRight:'8%',paddingBottom:'38%'};
        box={...base,fontSize:66,maxWidth:'84%',textAlign:'center',padding:'18px 26px',borderRadius:20,
          background:'linear-gradient(135deg,rgba(6,20,34,.9),rgba(8,41,57,.82))',border:'2px solid rgba(91,225,255,.76)',boxShadow:'0 18px 50px rgba(0,0,0,.48)'};
      }else if(variant==='lower_third'){
        wrap={...wrap,justifyContent:'flex-end',paddingBottom:(bottom*100+15)+'%',paddingTop:0};
        box={...box,fontSize:36,borderLeft:'8px solid #32d7ff',borderTop:'1px solid rgba(90,220,255,.55)'};
      }else if(variant==='callout'){
        wrap={...wrap,alignItems:'flex-end',paddingLeft:'14%',paddingRight:'7%'};
        box={...box,fontSize:34,borderRadius:28,backgroundColor:'rgba(7,24,34,.9)'};
      }else if(variant==='badge'){
        wrap={...wrap,alignItems:'center',paddingLeft:'12%',paddingRight:'12%'};
        box={...base,fontSize:31,borderRadius:999,padding:'11px 22px',backgroundColor:'rgba(13,63,78,.92)',border:'2px solid rgba(101,234,255,.75)',boxShadow:'0 12px 35px rgba(0,0,0,.4)'};
      }
      return <Sequence key={"g"+i} from={from} durationInFrames={dur}>
        <AbsoluteFill style={wrap}>
          <div style={box}>
            {variant==='callout'&&<span style={{display:'inline-block',width:13,height:13,borderRadius:'50%',background:'#55e7ff',boxShadow:'0 0 18px #55e7ff',marginRight:13}}/>}
            {g.text}
            {variant==='kinetic_title'&&<div style={{height:5,width:Math.max(80,visible*340),background:'linear-gradient(90deg,#39d6ff,#55ed9b)',borderRadius:99,margin:'13px auto 0'}}/>}
          </div>
        </AbsoluteFill>
      </Sequence>
    })}
  </AbsoluteFill>
};

const RemotionRoot:React.FC=()=>(
  <Composition
    id="MediaFinish"
    component={MediaFinish}
    durationInFrames={300}
    fps={30}
    width={1080}
    height={1920}
    calculateMetadata={({props}:any)=>({
      durationInFrames:Math.max(1,Number(props.durationInFrames||300)),
      fps:Number(props.fps||30),width:Number(props.width||1080),height:Number(props.height||1920)
    })}
    defaultProps={{videoPath:'',captions:[],motion:[],graphics:[],safeZones:{top:.12,bottom:.20,right:.12,left:0},fps:30,durationInFrames:300,width:1080,height:1920}}
  />
);

registerRoot(RemotionRoot);
