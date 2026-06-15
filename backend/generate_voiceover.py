import os
import sys
import asyncio
import edge_tts
from moviepy import VideoFileClip, AudioFileClip

# Reconfigure stdout/stderr for Windows UTF-8 compatibility
if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# Supported student branding profiles
PROFILES = {
    "sarah_nguyen": {
        "voice": "en-US-EmmaMultilingualNeural",
        "input_video": "sarah_nguyen_cancer_mutations.webm",
        "output_video": "sarah_nguyen_cancer_mutations_voiceover.mp4",
        "segments": [
            "Finding a funded research lab at Stanford used to be impossible. Let me show you how I did it.",
            "First, I uploaded my academic CV and detailed my specific research interests in genomics and somatic cancer mutations.",
            "In just two seconds, the AI synthesized my credentials and calculated my compatibility matches.",
            "The first match at UC Berkeley was robotics. Not a fit, so I skipped it.",
            "The next match was perfect: Dr. Jenkins' lab at Stanford, a ninety-eight percent home campus match studying genomic splicing. Let's draft an outreach email.",
            "LabMatch generated a highly tailored pitch citing specific cancer methodologies. Secure integration is just one click away. Match your own CV now, link is in my bio!"
        ]
    },
    "elena_rostova": {
        "voice": "en-US-EmmaMultilingualNeural",
        "input_video": "elena_rostova_crispr_editing.webm",
        "output_video": "elena_rostova_crispr_editing_voiceover.mp4",
        "segments": [
            "Finding a funded CRISPR editing placement at Harvard used to take months. Watch how I did it.",
            "First, I uploaded my molecular biology CV and input my specific interests in stem cell screening.",
            "In just two seconds, the AI synthesized my credentials and calculated my compatibility matches.",
            "The first match at MIT was plant biology. Not a fit, so I skipped it.",
            "The next match was a perfect ninety-eight percent home campus match: Dr. Sternberg's base editing lab. Let's draft an outreach email.",
            "LabMatch generated a highly tailored cover letter citing specific epigenetic methodologies. Secure integration is just one click away. Find your funded lab placement today, link in bio!"
        ]
    }
}

async def generate_voiceover(profile="sarah_nguyen"):
    if profile not in PROFILES:
        print(f"❌ Error: Profile '{profile}' not recognized!")
        return

    cfg = PROFILES[profile]
    voice = cfg["voice"]
    input_video_name = cfg["input_video"]
    output_video_name = cfg["output_video"]
    segments = cfg["segments"]

    print("==================================================")
    print(" 🎙️ LABMATCH AI AUTOMATED AI VOICEOVER GENERATOR ")
    print("==================================================")
    
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    videos_dir = os.path.join(root_dir, "backend", "videos")
    os.makedirs(videos_dir, exist_ok=True)
    
    input_video_path = os.path.join(videos_dir, input_video_name)
    output_video_path = os.path.join(videos_dir, output_video_name)
    
    if not os.path.exists(input_video_path):
        print(f"❌ Error: Input video file not found at: {input_video_path}")
        return
        
    print(f"🎥 Input video: {input_video_path}")
    print(f"🗣️ Voice: {voice}")
    
    # 1. Synthesize text narrative segments to temporary audio files
    print("\n[STEP 1] Generating premium AI narration segments...")
    audio_clips = []
    
    for i, text in enumerate(segments):
        audio_filename = f"segment_{i}.mp3"
        audio_path = os.path.join(videos_dir, audio_filename)
        
        print(f"  🎙️ Synthesizing segment {i+1}/{len(segments)}...")
        
        # Edge TTS async synthesis
        communicate = edge_tts.Communicate(text, voice, rate="+20%")
        await communicate.save(audio_path)
        audio_clips.append(audio_path)
        
    # 2. Combine synthesized segments into a single audio file with silence gaps
    print("\n[STEP 2] Formatting full narration audio pipeline...")
    temp_full_audio_path = os.path.join(videos_dir, "full_narration.mp3")
    
    # Use moviepy to concatenate audio segments with correct pacing
    from moviepy import AudioFileClip, concatenate_audioclips
    
    clips = []
    # Video segment milestones
    # Onboarding starts: 0.0s
    # Onboarding details complete: 16s
    # Synthesis page: 24s
    # Deck review card 1: 30s
    # Card 2 Stanford: 38s
    # Outreach Composer: 46s
    
    # We will build a timed audiotrack synced to the video pacing
    # Narrative starts immediately
    seg1 = AudioFileClip(audio_clips[0])
    
    # Narrative 2 starts around 7.5s (Get started click)
    # Narrative 3 starts around 21.0s (Submit click / Synthesis load)
    # Narrative 4 starts around 29.5s (Dashboard load / Card 1)
    # Narrative 5 starts around 38.0s (Card 2 Stanford load)
    # Narrative 6 starts around 49.0s (Composer load)
    
    # Generate full audio mix
    # We will place segments at custom onset milestones using moviepy's set_start helper
    mixed_audio = None
    c1 = None
    c2 = None
    c3 = None
    c4 = None
    c5 = None
    c6 = None
    
    try:
        c1 = AudioFileClip(audio_clips[0]).with_start(0.2)
        c2 = AudioFileClip(audio_clips[1]).with_start(5.5)
        c3 = AudioFileClip(audio_clips[2]).with_start(12.5)
        c4 = AudioFileClip(audio_clips[3]).with_start(18.5)
        c5 = AudioFileClip(audio_clips[4]).with_start(23.7)
        c6 = AudioFileClip(audio_clips[5]).with_start(32.5)
        
        from moviepy import CompositeAudioClip
        mixed_audio = CompositeAudioClip([c1, c2, c3, c4, c5, c6])
        mixed_audio.write_audiofile(temp_full_audio_path, fps=44100)
        print("✅ Premium text-to-speech audio compiled!")
        
    except Exception as audio_err:
        print(f"❌ Error during audio mixing: {audio_err}")
        return
    finally:
        # Close all temp clip readers to release Windows file handles
        for c in [c1, c2, c3, c4, c5, c6, mixed_audio]:
            if c:
                try:
                    c.close()
                except Exception:
                    pass

    # 3. Multiplex audio into the vertical mobile video using MoviePy
    print("\n[STEP 3] Programmatically merging audio track with vertical video...")
    video_clip = None
    audio_clip = None
    final_audio = None
    final_video = None
    try:
        video_clip = VideoFileClip(input_video_path).resized(width=1080, height=1920)
        audio_clip = AudioFileClip(temp_full_audio_path)
        
        # Crop to the minimum of audio or video duration to prevent out-of-bound errors
        final_duration = min(video_clip.duration, audio_clip.duration)
        final_video = video_clip.with_duration(final_duration).with_audio(audio_clip.with_duration(final_duration))
        
        print("🎬 Rendering combined audio-video file...")
        final_video.write_videofile(
            output_video_path,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=os.path.join(videos_dir, "temp-audio.m4a"),
            remove_temp=True,
            fps=30
        )
        
        # Close handles to allow cleanup
        try:
            if final_video: final_video.close()
            if final_audio: final_audio.close()
            if audio_clip: audio_clip.close()
            if video_clip: video_clip.close()
        except Exception:
            pass
            
        # Cleanup segment files
        print("\n[STEP 4] Cleaning up intermediate narration assets...")
        for path in audio_clips:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as del_err:
                    print(f"[WARNING] Failed to remove segment file: {path}. Reason: {del_err}")
        if os.path.exists(temp_full_audio_path):
            try:
                os.remove(temp_full_audio_path)
            except Exception as del_err:
                print(f"[WARNING] Failed to remove full_narration: {temp_full_audio_path}. Reason: {del_err}")
            
        print("\n==================================================")
        print(" 🎉 SUCCESS: AI Voiceover Combined Successfully! ")
        print("==================================================")
        print("Your final voiceover TikTok video has been saved to:")
        print(f"👉 {output_video_path}")
        print("==================================================")
        
    except Exception as multiplex_err:
        print(f"❌ Error multiplexing audio-video: {multiplex_err}")
    finally:
        try:
            if final_video: final_video.close()
            if final_audio: final_audio.close()
            if audio_clip: audio_clip.close()
            if video_clip: video_clip.close()
        except Exception:
            pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LabMatch AI Video Voiceover Multiplexer")
    parser.add_argument("--profile", default="sarah_nguyen", choices=list(PROFILES.keys()), help="Target student profile key")
    args = parser.parse_args()
    
    asyncio.run(generate_voiceover(args.profile))
