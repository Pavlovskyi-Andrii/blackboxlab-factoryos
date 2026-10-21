import React from 'react';
import {AbsoluteFill, Composition, Sequence, staticFile, useCurrentFrame, interpolate, OffthreadVideo, registerRoot} from 'remotion';

type Caption={start:number;end:number;text:string;keyword?:string};
type Motion={start:number;end:number;type:string;zoom:number};
type Graphic={start:number;end:number;text:string};
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
      return <Sequence key={"g"+i} from={from} durationInFrames={dur}>
        <AbsoluteFill style={{justifyContent:'flex-start',alignItems:'flex-start',paddingTop:(top*100+4)+'%',paddingLeft:'8%',paddingRight:'14%',pointerEvents:'none'}}>
          <div style={{backgroundColor:'rgba(5,18,28,.88)',border:'2px solid rgba(112,229,255,.6)',borderRadius:14,padding:'12px 18px',fontFamily:'DejaVu Sans, sans-serif',fontWeight:800,fontSize:38,color:'#eafaff',boxShadow:'0 12px 34px rgba(0,0,0,.45)'}}>{g.text}</div>
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
