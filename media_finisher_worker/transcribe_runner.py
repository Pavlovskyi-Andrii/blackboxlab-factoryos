import json
import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 6:
        raise SystemExit("usage: transcribe_runner WAV OUTPUT_JSON MODEL DEVICE COMPUTE_TYPE")
    wav=Path(sys.argv[1])
    output=Path(sys.argv[2])
    model_name,device,compute_type=sys.argv[3:6]

    from faster_whisper import WhisperModel

    model=WhisperModel(model_name,device=device,compute_type=compute_type)
    segments,info=model.transcribe(str(wav),word_timestamps=True,vad_filter=True)
    words=[]
    for segment in segments:
        for word in segment.words or []:
            token=str(word.word or "").strip()
            if not token or word.start is None or word.end is None:
                continue
            words.append({
                "word":token,
                "start":round(float(word.start),3),
                "end":round(float(word.end),3),
                "confidence":round(float(word.probability or 0),4),
            })
    payload={
        "words":words,
        "meta":{
            "language":getattr(info,"language",None),
            "language_probability":getattr(info,"language_probability",None),
            "model":model_name,
            "process_isolated":True,
        },
    }
    output.write_text(json.dumps(payload,ensure_ascii=False),encoding="utf-8")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
