import os
import sys
import asyncio
import uuid
from playwright.async_api import async_playwright

# Reconfigure stdout/stderr for Windows UTF-8 compatibility
if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

async def capture_views():
    print("==================================================")
    print("   📸 LABMATCH AI VIEW CAPTURE & AUDIT ENGINE   ")
    print("==================================================")

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pdf_path = os.path.join(root_dir, "backend", "test_resume.pdf")
    screenshots_dir = os.path.join(root_dir, "backend", "screenshots_debug")
    
    os.makedirs(screenshots_dir, exist_ok=True)
    
    print(f"📄 Resume PDF path: {pdf_path}")
    print(f"📂 Output screenshots folder: {screenshots_dir}")
    if not os.path.exists(pdf_path):
        print("❌ Error: test_resume.pdf not found in backend/ directory.")
        return

    async with async_playwright() as p:
        print("\n[STEP 1] Launching Chromium in headless mode...")
        browser = await p.chromium.launch(headless=True)
        
        # Configure viewport to match TikTok mobile dimensions (exact 9:16)
        context = await browser.new_context(
            viewport={"width": 540, "height": 960}, # Exact 9:16 vertical aspect ratio
            device_scale_factor=2
        )
        
        page = await context.new_page()
        
        # Step 2: Open frontend Onboarding page
        print("\n[STEP 2] Navigating to LabMatch AI...")
        await page.goto("http://localhost:5173/")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(1.0)
        
        # Take cover page screenshot
        await page.screenshot(path=os.path.join(screenshots_dir, "01_cover_page.png"))
        print("📸 Captured 01_cover_page.png")

        # Click Get started
        await page.locator("text=Get started").first.click()
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(1.0)
        
        # Screenshot of empty onboarding
        await page.screenshot(path=os.path.join(screenshots_dir, "02_onboarding_empty.png"))
        print("📸 Captured 02_onboarding_empty.png")

        # Step 3: Upload the resume PDF
        print("\n[STEP 3] Uploading CV PDF...")
        file_input = page.locator("input[type='file']")
        await file_input.set_input_files(pdf_path)
        
        # Awaiting CV parsing success state (the Replace button appears)
        await page.wait_for_selector("text=Replace", timeout=15000)
        print("✅ Resume parsed and synthesized in the background!")
        await asyncio.sleep(1.0)
        
        await page.screenshot(path=os.path.join(screenshots_dir, "03_onboarding_cv_uploaded.png"))
        print("📸 Captured 03_onboarding_cv_uploaded.png")

        # Step 4: Fill Student Profile details
        print("\n[STEP 4] Inputting research interests...")
        await page.locator("input[placeholder='Full Name']").fill("Sarah Nguyen")
        await asyncio.sleep(0.15)
        
        unique_email = f"sarah.nguyen.premed.{uuid.uuid4().hex[:4]}@stanford.edu"
        await page.locator("input[placeholder='Email Address']").fill(unique_email)
        await asyncio.sleep(0.15)
        
        await page.locator("input[placeholder='University / Affiliation']").fill("Stanford University")
        await asyncio.sleep(0.15)
        
        textarea = page.locator("textarea")
        narrative_text = (
            "I am a pre-med student at Stanford interested in deep learning models "
            "for genomics, somatic cancer mutations, and transcription factor binding."
        )
        await textarea.fill(narrative_text)
        await asyncio.sleep(0.5)
        
        await page.screenshot(path=os.path.join(screenshots_dir, "04_onboarding_filled_top.png"))
        print("📸 Captured 04_onboarding_filled_top.png")

        # Scroll onboarding form down gradually to reveal suggested badges
        print("📜 Scrolling down onboarding form...")
        await page.evaluate("window.scrollBy(0, 300)")
        await asyncio.sleep(0.5)
        
        await page.screenshot(path=os.path.join(screenshots_dir, "05_onboarding_filled_middle.png"))
        print("📸 Captured 05_onboarding_filled_middle.png")

        # Click oncology badge
        print("💡 Appending oncology tags...")
        await page.locator("text=+ Somatic mutations in glioma").click()
        await asyncio.sleep(0.5)
        
        # Scroll all the way to show the submit button
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.5)
        await page.screenshot(path=os.path.join(screenshots_dir, "06_onboarding_filled_bottom.png"))
        print("📸 Captured 06_onboarding_filled_bottom.png")

        # Step 5: Click Analyze and Sync
        print("\n[STEP 5] Clicking 'Analyze & Sync Matches'...")
        await page.locator("button[type='submit']").click()
        
        print("🧬 Querying pgvector similarity...")
        # Wait for intermediate Profile Synthesized page to render
        await page.wait_for_selector("text=Profile Synthesized Successfully!", timeout=25000)
        print("🎉 Synthesis complete!")
        await asyncio.sleep(1.0)
        
        # Screenshot of success page top
        await page.screenshot(path=os.path.join(screenshots_dir, "07_synthesis_success_top.png"))
        print("📸 Captured 07_synthesis_success_top.png")
        
        # Scroll down success page
        await page.evaluate("window.scrollBy(0, 450)")
        await asyncio.sleep(0.5)
        await page.screenshot(path=os.path.join(screenshots_dir, "08_synthesis_success_bottom.png"))
        print("📸 Captured 08_synthesis_success_bottom.png")
        
        # Click the Skip & View Matches button to advance to the dashboard
        print("⏩ Entering matches dashboard...")
        await page.locator("text=Skip & View Matches directly ➔").click()
        
        # Wait for the swipe deck dashboard to load
        await page.wait_for_selector("text=Saved Labs", timeout=25000)
        await asyncio.sleep(2.0)
        
        # Capture Card 1 UC Berkeley
        print("🔍 Capturing Card 1: UC Berkeley...")
        await page.screenshot(path=os.path.join(screenshots_dir, "09_card1_top.png"))
        print("📸 Captured 09_card1_top.png")
        
        # Scroll card/page down to verify if Skip/Heart buttons are visible
        await page.evaluate("window.scrollBy(0, 300)")
        await asyncio.sleep(0.5)
        await page.screenshot(path=os.path.join(screenshots_dir, "10_card1_bottom.png"))
        print("📸 Captured 10_card1_bottom.png")
        
        # Scroll page back up
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.2)
        
        # Click the X button (Skip Lab) to dismiss the first card
        print("🖱️ Clicking 'Skip Lab' button (X)...")
        await page.locator("button[title='Skip Lab']").click()
        await asyncio.sleep(2.0) # Wait for slide transition
        
        # Capture Card 2 Stanford University
        print("🔍 Capturing Card 2: Stanford University...")
        await page.screenshot(path=os.path.join(screenshots_dir, "11_card2_top.png"))
        print("📸 Captured 11_card2_top.png")
        
        # Scroll Card 2 down to verify outreach buttons visibility
        await page.evaluate("window.scrollBy(0, 300)")
        await asyncio.sleep(0.5)
        await page.screenshot(path=os.path.join(screenshots_dir, "12_card2_bottom.png"))
        print("📸 Captured 12_card2_bottom.png")
        
        # Click 'Draft Cold Outreach' directly on Card 2
        print("\n[STEP 6] Accessing Outreach Composer...")
        await page.locator("button:has-text('Draft Cold Outreach')").first.scroll_into_view_if_needed()
        await page.locator("button:has-text('Draft Cold Outreach')").first.click()
        
        # Wait for outreach workspace to load
        await page.wait_for_selector("text=Outreach Synthesis Workspace", timeout=15000)
        await asyncio.sleep(2.0)
        
        # Screenshot of Composer top
        await page.screenshot(path=os.path.join(screenshots_dir, "13_composer_top.png"))
        print("📸 Captured 13_composer_top.png")
        
        # Scroll composer down to show email body textarea and send buttons
        await page.evaluate("window.scrollBy(0, 380)")
        await asyncio.sleep(0.5)
        await page.screenshot(path=os.path.join(screenshots_dir, "14_composer_bottom.png"))
        print("📸 Captured 14_composer_bottom.png")
        
        # Scroll email body text area down
        print("📜 Scrolling draft email body...")
        await page.evaluate("document.querySelector('textarea').scrollBy(0, 150)")
        await asyncio.sleep(0.5)
        await page.screenshot(path=os.path.join(screenshots_dir, "15_composer_textarea_scrolled.png"))
        print("📸 Captured 15_composer_textarea_scrolled.png")
        
        # Final connection state hover / check
        connect_btn = page.locator("button:has-text('Connect Gmail Account')")
        if await connect_btn.count() > 0:
            print("💡 Connect Gmail Account button is present!")
        else:
            print("💡 Send via Gmail button is present!")
            
        await context.close()
        await browser.close()
        print("\n==================================================")
        print("  🎉 SUCCESS: All views captured and saved!")
        print("==================================================")

if __name__ == "__main__":
    asyncio.run(capture_views())
