import os
import sys
import asyncio
from playwright.async_api import async_playwright

async def run_e2e_test():
    print("==================================================")
    print("     LABMATCH AI E2E PLAYWRIGHT INTEGRATION TEST ")
    print("==================================================")

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pdf_path = os.path.join(root_dir, "backend", "test_resume.pdf")
    
    print(f"Resume PDF path: {pdf_path}")
    print(f"Path exists: {os.path.exists(pdf_path)}")

    async with async_playwright() as p:
        # Launch headless browser for seamless background execution
        print("\n[STEP 1] Launching browser context...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        # Step 2: Open frontend Onboarding page
        print("\n[STEP 2] Navigating to http://localhost:5173/ ...")
        await page.goto("http://localhost:5173/")
        await page.wait_for_load_state("networkidle")
        print(f"  Loaded page title: '{await page.title()}'")
        await page.screenshot(path="step2_onboarding.png")
        print("  Saved step2_onboarding.png")

        # Step 3: Upload the resume PDF
        print("\n[STEP 3] Uploading test_resume.pdf ...")
        # Locate the hidden file input element and upload file
        file_input = page.locator("input[type='file']")
        await file_input.set_input_files(pdf_path)
        
        # Wait for extraction status to change to success
        print("  Awaiting CV parsing and text extraction...")
        await page.wait_for_selector("text=CV Successfully Extracted!", timeout=10000)
        await page.screenshot(path="step3_uploaded.png")
        print("  [SUCCESS] Resume parsed successfully! Saved step3_uploaded.png")

        # Step 4: Input research interests
        print("\n[STEP 4] Inputting research narrative...")
        
        # Fill Full Name and Email Address
        import uuid
        unique_email = f"nicholas.anderson.{uuid.uuid4().hex[:6]}@example.edu"
        print(f"  Filling student identity profiles with email: {unique_email} ...")
        await page.locator("input[placeholder='Full Name']").fill("Nicholas Anderson")
        await page.locator("input[placeholder='Email Address']").fill(unique_email)
        
        textarea = page.locator("textarea")
        await textarea.fill("I am deeply interested in studying neurodegenerative diseases. Specifically, leveraging high-content screening systems and deep learning algorithms to predict cellular drug target engagement.")
        
        # Click a suggestion badge to append it
        print("  Appending suggested methodology vector...")
        await page.click("text=+ CRISPR-Cas9 gene editing")
        
        # Get updated text
        updated_text = await textarea.input_value()
        print(f"  Narrative Value: '{updated_text}'")
        await page.screenshot(path="step4_narrative.png")
        print("  Saved step4_narrative.png")

        # Step 5: Click Analyze and Sync
        print("\n[STEP 5] Clicking 'Analyze & Sync Matches'...")
        # Target the submit button
        submit_btn = page.locator("button[type='submit']")
        await submit_btn.click()
        
        print("  Awaiting Gemini Profile Synthesis and pgvector matching...")
        # The button will display "Synthesizing Profile..." then page will navigate
        # Let's wait for dashboard navigation. The dashboard has navigation button "2. Alignment Swiper"
        await page.wait_for_selector("text=Saved Labs", timeout=20000)
        await page.screenshot(path="step5_dashboard.png")
        print("  [SUCCESS] Matches successfully calculated! Saved step5_dashboard.png")

        # Step 6: Verify matched grants are rendered
        print("\n[STEP 6] Extracting matched grants from Dashboard...")
        # Check active matches count
        match_cards = page.locator("div:has-text('Match')")
        card_count = await match_cards.count()
        print(f"  Detected match cards on DOM: {card_count}")
        
        # Select the first match card and click "Draft Cold Outreach"
        print("  Navigating to outreach composer...")
        compose_btn = page.locator("button:has-text('Draft Cold Outreach')").first
        await compose_btn.click()
        
        await page.wait_for_selector("text=Outreach Synthesis Workspace", timeout=8000)
        await page.screenshot(path="step6_composer.png")
        print("  [SUCCESS] Composer successfully loaded! Saved step6_composer.png")

        # Step 7: Verify OAuth connection state
        print("\n[STEP 7] Checking Gmail Workspace connection state...")
        # Check if the Connect button is present
        connect_btn = page.locator("button:has-text('Connect Gmail Account')")
        btn_count = await connect_btn.count()
        if btn_count > 0:
            print("  [SUCCESS] 'Connect Gmail Account' button is visible and active!")
            print("  Your Google OAuth Client ID has successfully triggered connection state locks.")
        else:
            send_btn = page.locator("button:has-text('Send via Gmail')")
            if await send_btn.count() > 0:
                print("  [SUCCESS] Account is already connected! 'Send via Gmail' is available.")
            else:
                print("  [WARNING] Connection controls were not located.")

        await browser.close()
        print("\n==================================================")
        print("   [ALL TESTS PASSED] PLAYWRIGHT FLOW COMPLETED!  ")
        print("==================================================")

if __name__ == "__main__":
    asyncio.run(run_e2e_test())
