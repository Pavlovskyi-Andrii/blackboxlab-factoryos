from media_finisher_worker.app import build_cut_list, map_words_after_cuts, group_captions, _graphics_timeline, _short_clip_windows, _motion_timeline
from media_finisher_worker.edit_decisions import plan_edits

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

tail_words=[{"word":"one","start":0.0,"end":0.4},{"word":"two.","start":0.42,"end":0.8},{"word":"three","start":0.82,"end":1.2}]
tail_caps=group_captions(tail_words,profile,[0.81])
assert len(tail_caps)==2 and tail_caps[0]["end"]==0.81, "a caption tail must stop at the cut"
assert all(a["end"]<=b["start"] for a,b in zip(tail_caps,tail_caps[1:])), "caption groups must not be on screen together"

motion_cuts=[{"start":1.0,"end":1.1},{"start":5.0,"end":6.0},{"start":6.3,"end":7.0},{"start":12.0,"end":13.0}]
jumps=[x for x in _motion_timeline(20.0,motion_cuts,{"motion":{}}) if x["type"]=="jump_cut_mask_zoom"]
assert [round(x["start"],2) for x in jumps]==[4.84,10.14], "zoom only on a visible jump, and not twice within 0.8s"

audit_plan=plan_edits([{"start":0.7,"end":1.7,"reason":"silence>0.4s"}],words,3.0,profile)
assert audit_plan["cuts"]==cuts and audit_plan["decisions"][0]["applied"], "build_cut_list must be the applied part of the decision list"
print("Media Finisher planner tests passed")
