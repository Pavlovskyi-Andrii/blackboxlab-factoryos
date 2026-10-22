from media_finisher_worker.app import build_cut_list, map_words_after_cuts, group_captions, _graphics_timeline, _short_clip_windows

profile={
  "speech_cleanup":{"silence_trim":True,"pre_handle_sec":0.1,"post_handle_sec":0.15,"semantic_duplicate_planner":True},
  "captions":{"max_words":3},
}
words=[
 {"word":"hello","start":0.0,"end":0.3,"confidence":1},
 {"word":"world","start":0.32,"end":0.6,"confidence":1},
 {"word":"again","start":1.8,"end":2.1,"confidence":1},
 {"word":"again","start":2.12,"end":2.4,"confidence":1},
]
cuts=build_cut_list([{"start":0.7,"end":1.7,"reason":"silence>0.4s"}],words,3.0,profile)
assert cuts and round(cuts[0]["start"],2)==0.8 and round(cuts[0]["end"],2)==1.55
mapped=map_words_after_cuts(words,cuts)
assert len(mapped)==4 and mapped[2]["start"]<1.1
caps=group_captions(mapped,profile,[0.8])
assert caps and all(1<=len(x["words"])<=3 for x in caps)
manual={"_factoryos_manual_raw":True,"scenes":[],"title":""}
graphics=_graphics_timeline(manual,8.0,{"graphics":{"emphasis_max":3,"duration_max_sec":2.0}},mapped)
assert graphics and all(x["type"]=="transcript_exact_emphasis" for x in graphics)
source_words={x["word"] for x in mapped}
assert all(x["text"] in source_words for x in graphics), "manual raw graphics must use exact transcript words"

assert all(x.get("variant") in {"kinetic_title","lower_third","callout","badge"} for x in graphics), "motion graphic variants missing"

filler_words=[
 {"word":"Привет","start":0.0,"end":0.35,"confidence":.99},
 {"word":"э","start":0.42,"end":0.67,"confidence":.97},
 {"word":"мир","start":0.75,"end":1.05,"confidence":.99},
 {"word":"эм","start":1.18,"end":1.42,"confidence":.96},
 {"word":"дальше","start":1.50,"end":1.9,"confidence":.99},
]
filler_cuts=build_cut_list([],filler_words,2.2,{"speech_cleanup":{"silence_trim":False,"filler_trim":True,"semantic_duplicate_planner":False}})
assert len(filler_cuts)==2 and all("filler_word:" in x["reason"] for x in filler_cuts), "filler-word cleanup regression"

long_words=[]
for i in range(240):
    start=i*0.5
    token=("important" if i%9==0 else "context" if i%5==0 else "word")+str(i)
    long_words.append({"word":token,"start":start,"end":start+0.3,"confidence":1})
shorts=_short_clip_windows(long_words,120.0,3)
assert 1<=len(shorts)<=3
assert all(0<=x["start_sec"]<x["end_sec"]<=120.0 for x in shorts)
assert shorts==sorted(shorts,key=lambda x:x["start_sec"])
print("Media Finisher planner tests passed")
