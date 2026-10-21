from media_finisher_worker.app import build_cut_list, map_words_after_cuts, group_captions

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
print("Media Finisher planner tests passed")
