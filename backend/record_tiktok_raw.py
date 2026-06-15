import os
import sys
import asyncio
import uuid
import math
from playwright.async_api import async_playwright

# Reconfigure stdout/stderr for Windows UTF-8 compatibility
if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


# Helper function to generate a smooth Bezier curve path between two points
def calculate_bezier_path(start, end, steps=25):
    path = []
    # Dynamic control points to add a realistic curved drift to the mouse path
    ctrl_x = start[0] + (end[0] - start[0]) * 0.3 + 45
    ctrl_y = start[1] + (end[1] - start[1]) * 0.7 - 25
    
    for i in range(steps + 1):
        t = i / steps
        # Quadratic Bezier formula
        x = (1 - t)**2 * start[0] + 2 * (1 - t) * t * ctrl_x + t**2 * end[0]
        y = (1 - t)**2 * start[1] + 2 * (1 - t) * t * ctrl_y + t**2 * end[1]
        path.append((int(x), int(y)))
    return path

# High-fidelity custom mouse controller for realistic visual walkthrough recordings
class SmoothVisualCursor:
    def __init__(self, page):
        self.page = page
        self.current_pos = (200, 400) # Start default position in viewport center

    async def move_to(self, selector, steps=15): # Reduced steps from 30 for 50% faster glide speeds!
        # Locate the element and retrieve its absolute bounding box coordinate center
        element = self.page.locator(selector).first
        await element.wait_for(state="visible", timeout=12000)
        box = await element.bounding_box()
        if not box:
            print(f"[WARNING] Bounding box empty for selector: {selector}")
            return
            
        target_x = box["x"] + box["width"] / 2
        target_y = box["y"] + box["height"] / 2
        
        # Calculate intermediate coordinates
        path = calculate_bezier_path(self.current_pos, (target_x, target_y), steps)
        
        # Execute smooth incremental mouse slide paths
        for x, y in path:
            await self.page.mouse.move(x, y)
            await asyncio.sleep(0.006) # Halved tick delays to accelerate visual glides
            
        self.current_pos = (target_x, target_y)
        await asyncio.sleep(0.08) # Decelerate buffer

    async def click_on(self, selector):
        try:
            await self.move_to(selector, steps=12) # Faster movement before tapping
            await self.page.mouse.down()
            await asyncio.sleep(0.06) # Halved touch dwell timing
            await self.page.mouse.up()
        except Exception as e:
            print(f"[FALLBACK] Direct selector click backup for: {selector}. Reason: {e}")
            # Coordinate-safe native fallback if bounding box is outside view/off-center
            await self.page.locator(selector).first.click()
            
        await asyncio.sleep(0.2)  # Halved post-click verification buffer

    async def scroll_window(self, delta_y, steps=22): # Accelerated scrolls
        # Gradual micro-scrolling step adjustments to avoid jarring snaps
        step_scroll = delta_y / steps
        for _ in range(steps):
            # Injecting scroll offset directly into DOM context for precise pixel pacing
            await self.page.evaluate(f"window.scrollBy(0, {step_scroll})")
            await asyncio.sleep(0.008)
        await asyncio.sleep(0.15)
        
    async def reset_view(self):
        # Force browser viewport to scroll perfectly to the top
        await self.page.evaluate("window.scrollTo(0, 0)")
        # Reset visual cursor position state to prevent coordinate drift
        self.current_pos = (200, 250)
        await self.page.mouse.move(200, 250)
        await asyncio.sleep(0.1)

    async def scroll_element(self, selector, delta_y, steps=40):
        step_scroll = delta_y / steps
        await self.page.locator(selector).first.wait_for(state="visible")
        for _ in range(steps):
            await self.page.evaluate(
                f"document.querySelector('{selector}').scrollBy(0, {step_scroll})"
            )
            await asyncio.sleep(0.015)
        await asyncio.sleep(0.3)

async def record_tiktok_video(args=None):
    if args is None:
        class DefaultArgs:
            name = "Sarah Nguyen"
            email_prefix = "sarah.nguyen.premed"
            email_domain = "stanford.edu"
            university = "Stanford University"
            interests = (
                "I am a pre-med student at Stanford interested in deep learning models "
                "for genomics, somatic cancer mutations, and transcription factor binding."
            )
            badge = "+ Somatic mutations in glioma"
            output_prefix = "sarah_nguyen_cancer_mutations"
            headful = False
        args = DefaultArgs()
    print("==================================================")
    print("   🎬 LABMATCH AI TIKTOK VIDEO RECORDING ENGINE   ")
    print("==================================================")
    print("This script will launch a headful browser configured in")
    print("vertical mobile aspect ratio (1080x1920) and record the")
    print("entire application onboarding and outreach dispatch flow.")
    print("==================================================")

    # 1. Setup paths
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pdf_path = os.path.join(root_dir, "backend", "test_resume.pdf")
    videos_dir = os.path.join(root_dir, "backend", "videos")
    
    os.makedirs(videos_dir, exist_ok=True)
    
    print(f"📄 Resume PDF path: {pdf_path}")
    print(f"📂 Output videos folder: {videos_dir}")
    if not os.path.exists(pdf_path):
        print("❌ Error: test_resume.pdf not found in backend/ directory. Please ensure it exists.")
        return

    async with async_playwright() as p:
        headless_mode = not getattr(args, "headful", False)
        mode_str = "headless" if headless_mode else "headful"
        print(f"\n[STEP 1] Launching Chromium in {mode_str} mode...")
        # slow_mo is handled manually by our smooth controller to ensure cinematic motion
        browser = await p.chromium.launch(
            headless=headless_mode
        )
        
        # Configure the mobile viewport and native Playwright video recording
        print("🎥 Setting viewport to vertical 9:16 mobile format & starting screen capture...")
        context = await browser.new_context(
            viewport={"width": 540, "height": 960}, # Exact 9:16 vertical aspect ratio
            device_scale_factor=2,                  # High-DPI crystal-clear resolution
            record_video_dir=videos_dir,
            record_video_size={"width": 540, "height": 960} # Match viewport size exactly to ensure full-bleed capture
        )
        
        page = await context.new_page()
        cursor = SmoothVisualCursor(page)
        
        # Inject custom premium teal virtual mouse pointer / touch indicator for visual feedback
        await page.add_init_script("""
            window.addEventListener('DOMContentLoaded', () => {
                const box = document.createElement('div');
                box.id = 'playwright-mouse-pointer';
                box.style = 'position: absolute; width: 22px; height: 22px; background: rgba(13, 92, 92, 0.4); border: 2px solid #0d5c5c; border-radius: 50%; pointer-events: none; z-index: 100000; transition: transform 0.1s, background 0.1s, left 0.05s ease, top 0.05s ease; transform: translate(-50%, -50%);';
                document.body.appendChild(box);
                
                document.addEventListener('mousemove', e => {
                    box.style.left = e.pageX + 'px';
                    box.style.top = e.pageY + 'px';
                });
                
                document.addEventListener('mousedown', () => {
                    box.style.background = 'rgba(13, 92, 92, 0.85)';
                    box.style.transform = 'translate(-50%, -50%) scale(1.4)';
                });
                
                document.addEventListener('mouseup', () => {
                    box.style.background = 'rgba(13, 92, 92, 0.4)';
                    box.style.transform = 'translate(-50%, -50%) scale(1)';
                });
            });
        """)

        # Step 2: Open frontend Onboarding page
        print("\n[STEP 2] Navigating to LabMatch AI...")
        await page.goto("http://localhost:5173/")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(0.75)

        # Click Get started smoothly to go to onboarding
        print("🖱️ Sliding to 'Get started' button...")
        await cursor.click_on("text=Get started")
        await asyncio.sleep(0.5)

        # Step 3: Upload the resume PDF
        print("\n[STEP 3] Uploading CV PDF...")
        # Move cursor over file upload box first to draw visual focus
        await cursor.move_to("text=Upload Academic CV / Resume (PDF)")
        await asyncio.sleep(0.2)
        
        file_input = page.locator("input[type='file']")
        await file_input.set_input_files(pdf_path)
        
        # Awaiting CV parsing success state (the Replace button appears)
        await page.wait_for_selector("text=Replace", timeout=15000)
        print("✅ Resume parsed and synthesized in the background!")
        await asyncio.sleep(0.75)

        # Step 4: Fill Student Profile details
        print("\n[STEP 4] Inputting research interests...")
        
        # Slide to Full Name field, click, and type
        await cursor.click_on("input[placeholder='Full Name']")
        await page.locator("input[placeholder='Full Name']").fill(args.name)
        await asyncio.sleep(0.15)
        
        # Slide to Email field, click, and type
        await cursor.click_on("input[placeholder='Email Address']")
        unique_email = f"{args.email_prefix}.{uuid.uuid4().hex[:4]}@{args.email_domain}"
        await page.locator("input[placeholder='Email Address']").fill(unique_email)
        await asyncio.sleep(0.15)
        
        # Slide to University field, click, and type
        await cursor.click_on("input[placeholder='University / Affiliation']")
        await page.locator("input[placeholder='University / Affiliation']").fill(args.university)
        await asyncio.sleep(0.15)
        
        # Slide to Research Interests textarea, click, and type
        await cursor.click_on("textarea")
        textarea = page.locator("textarea")
        narrative_text = args.interests
        await textarea.fill("")
        # Ultra fast character typing (delay=4ms)
        await textarea.type(narrative_text, delay=4)
        await asyncio.sleep(0.4)
        
        # Scroll onboarding form down gradually to reveal suggested badges
        print("📜 Gradually scrolling down onboarding form...")
        await cursor.scroll_window(260, steps=15)
        await asyncio.sleep(0.25)
        
        # Slide to suggested badge and click
        print(f"💡 Appending research tag: {args.badge}...")
        await cursor.click_on(f"text={args.badge}")
        await asyncio.sleep(0.4)

        # Step 5: Click Analyze and Sync
        await cursor.click_on("button[type='submit']")
        
        # Configure dynamic card text matching depending on the student profile
        if args.name == "Elena Rostova":
            card1_title = "Plant Genomes"
            card2_title = "Precision Epigenetic"
            card1_log = "Dr. Wei-An Lim (MIT)"
            card2_log = "Dr. Sternberg (Harvard University)"
        else:
            card1_title = "Autonomous Robotics"
            card2_title = "Deep Learning"
            card1_log = "Dr. Chen Wei (UC Berkeley)"
            card2_log = "Dr. Sarah Jenkins (Stanford University)"

        print("🧬 Querying pgvector similarity against NSF/NIH grants...")

        # Wait for intermediate Profile Synthesized page to render
        await page.wait_for_selector("text=Profile Synthesized Successfully!", timeout=25000)
        print("🎉 Synthesis complete! Pausing on secure pipeline setup...")
        # Reset scroll and coordinates state because this is a new route / page view transition!
        await cursor.reset_view()
        await asyncio.sleep(0.75) # Reduced wait time by 50%
        
        # Scroll down so the "Skip & View Matches directly ➔" link is fully in viewport/DOM bounds to resolve clicking bugs!
        print("📜 Scrolling down to reveal matches skip control...")
        await cursor.scroll_window(380, steps=20)
        await asyncio.sleep(0.15) # Reduced wait time by 50%
        
        # Click the Skip & View Matches button to advance to the dashboard
        print("⏩ Skipping authentication setup and entering matches dashboard...")
        await cursor.click_on("text=Skip & View Matches directly ➔")
        
        # Wait for the swipe deck dashboard to load
        await page.wait_for_selector("text=Saved Labs", timeout=25000)
        # Move directly to hover over the first card's title text to center attention
        await cursor.move_to(f"text={card1_title}", steps=15)
        await asyncio.sleep(1.0)
        
        # Step 5: High-fidelity active deck review sequence
        print(f"🔍 Presenting Card 1: {card1_log}...")
        # Hover cursor near the card center / title to draw viewer focus to the content
        await cursor.move_to(f"text={card1_title}", steps=10)
        await asyncio.sleep(2.5) # Cinema hold for 68% score
        
        # Scroll down to reveal Card 1 action buttons (Skip/Save)
        print("📜 Scrolling down to reveal Card 1 action controls...")
        await cursor.scroll_window(280, steps=18)
        await asyncio.sleep(1.2)

        
        # Click the X button (Skip Lab) to dismiss the first card
        print("🖱️ Sliding to 'Skip Lab' button (click X)...")
        await cursor.click_on("button[title='Skip Lab']")
        print("⏩ First card skipped successfully!")
        await asyncio.sleep(1.0) # Wait for slide out animation to begin
        
        # Scroll back up to the top before Card 2 details
        print("📜 Scrolling back to the top for the incoming card...")
        await cursor.scroll_window(-280, steps=18)
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)
        
        # We are now on Card 2 details
        print(f"🔍 Presenting Card 2: {card2_log}...")
        # Smoothly glide the mouse from bottom skip button directly to the card title to center focus
        await cursor.move_to(f"text={card2_title}", steps=15)
        await asyncio.sleep(3.0) # Cinematic hold for 98% Home Campus Match
        
        # Scroll down to reveal Card 2 action button (Draft Cold Outreach)
        print("📜 Scrolling down to reveal Card 2 outreach button...")
        await cursor.scroll_window(280, steps=18)
        await asyncio.sleep(1.2)
        
        # Click 'Draft Cold Outreach' directly on Card 2 to open Interactive Composer!
        print(f"\n[STEP 6] Accessing Outreach Composer directly from {card2_log} card...")
        await cursor.click_on("button:has-text('Draft Cold Outreach')")
        
        # Wait for interactive composer to load
        await page.wait_for_selector("text=Outreach Synthesis Workspace", timeout=15000)
        print("✍️ Opening Gemini Ghostwriter composer...")
        await asyncio.sleep(0.4) # Bypassed instantly for the video! Zero API delays.
        
        # Gradually scroll the email narrative composer so viewers can inspect the customized pitch
        print("📜 Gradually scrolling composer container downward to center outreach controls...")
        await cursor.scroll_window(360, steps=20)
        await asyncio.sleep(0.5)

        # Scroll the email textarea body gradually at a moderate pace to inspect the draft
        print("📜 Gradually scrolling email draft textarea body at moderate pace...")
        await cursor.scroll_element("textarea", 110, steps=25)
        await asyncio.sleep(4.0) # Legible paced hold for the finished email draft

        # Step 7: Highlight Connection flow
        print("\n[STEP 7] Highlighting secure Google integration flow...")
        # Slide smoothly to the Google login button to show where users sync accounts
        connect_btn = page.locator("button:has-text('Connect Gmail Account')")
        btn_count = await connect_btn.count()
        if btn_count > 0:
            await cursor.move_to("button:has-text('Connect Gmail Account')", steps=14)
            print("🔗 Smooth mouse hover over 'Connect Gmail Account' button complete!")
            await asyncio.sleep(0.5) # Bypassed to cut video 0.5s after hover!
        else:
            send_btn = page.locator("button:has-text('Send via Gmail')")
            if await send_btn.count() > 0:
                await cursor.move_to("button:has-text('Send via Gmail')", steps=14)
                print("✉️ Smooth mouse hover over active 'Send via Gmail' button complete!")
                await asyncio.sleep(0.5) # Bypassed to cut video 0.5s after hover!


        # Close page contexts to finish writing video output stream
        print("\n[STEP 8] Finalizing video record encoding...")
        video_path = await page.video.path()
        await context.close()
        await browser.close()
        
        # Rename/copy the recorded video file using output_prefix
        try:
            new_video_filename = f"{args.output_prefix}.webm"
            new_video_path = os.path.join(videos_dir, new_video_filename)
            
            import shutil
            if os.path.exists(video_path):
                shutil.copy(video_path, new_video_path)
                print(f"🎬 Video successfully saved and renamed to: {new_video_path}")
            else:
                print(f"[WARNING] Original video file not found at: {video_path}")
        except Exception as e:
            print(f"[WARNING] Failed to rename/copy video: {e}")
        
        print("\n==================================================")
        print(" 🎉 SUCCESS: TikTok Screen Recording Complete! ")
        print("==================================================")
        print("Your raw vertical HD TikTok recording has been saved to:")
        print(f"👉 {videos_dir}")
        print("Open the videos directory to check the recorded video file.")
        print("==================================================")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LabMatch AI TikTok Video Recording Engine")
    parser.add_argument("--name", default="Sarah Nguyen", help="Student Full Name")
    parser.add_argument("--email-prefix", default="sarah.nguyen.premed", help="Email Prefix")
    parser.add_argument("--email-domain", default="stanford.edu", help="Email Domain")
    parser.add_argument("--university", default="Stanford University", help="University Name")
    parser.add_argument("--interests", default="I am a pre-med student at Stanford interested in deep learning models for genomics, somatic cancer mutations, and transcription factor binding.", help="Research Interests Narrative")
    parser.add_argument("--badge", default="+ Somatic mutations in glioma", help="Skill Badge Text")
    parser.add_argument("--output-prefix", default="sarah_nguyen_cancer_mutations", help="Output file prefix")
    parser.add_argument("--headful", action="store_true", help="Launch browser in headful mode (visible window)")
    args = parser.parse_args()
    
    asyncio.run(record_tiktok_video(args))
