import os
import json
from playwright.async_api import async_playwright

EMAIL = os.getenv("ARENA_EMAIL")
PASSWORD = os.getenv("ARENA_PASSWORD")
SESSION_FILE = "session.json"

async def login_and_save_session():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]  # Important sur Render
        )
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto("https://arena.ai", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        for selector in ["button[aria-label*='menu' i]", "button:has(svg) >> nth=0"]:
            if await page.locator(selector).first.is_visible(timeout=2000):
                await page.locator(selector).first.click(); break
        await page.wait_for_timeout(1500)
        for selector in ["text=Log in", "button:has-text('Log in')"]:
            if await page.locator(selector).first.is_visible(timeout=2000):
                await page.locator(selector).first.click(); break
        await page.wait_for_timeout(2000)
        await page.locator("input[type='email']").first.fill(EMAIL)
        await page.wait_for_timeout(1000)
        for selector in ["button:has-text('Continue with Email')", "form:has(input[type='email']) button[type='submit']"]:
            if await page.locator(selector).first.is_visible(timeout=1500):
                await page.locator(selector).first.click(); break
        await page.wait_for_timeout(3000)
        pwd_input = page.locator("input[type='password']").first
        await pwd_input.fill(PASSWORD)
        await page.wait_for_timeout(1000)
        await pwd_input.press("Enter")
        await page.wait_for_timeout(5000)

        storage = await context.storage_state()
        with open(SESSION_FILE, "w") as f:
            json.dump(storage, f)
        await browser.close()
        print("✅ Session sauvegardée.")


async def send_prompt_to_ai(prompt: str, system_prompt: str = "") -> str:
    if not os.path.exists(SESSION_FILE):
        await login_and_save_session()

    full_prompt = f"[INSTRUCTIONS SYSTÈME : {system_prompt}]\n\n{prompt}" if system_prompt else prompt

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(storage_state=SESSION_FILE)
        page = await context.new_page()

        try:
            await page.goto("https://arena.ai/direct", wait_until="networkidle")
            await page.wait_for_timeout(3000)

            # Vérification : est-on toujours connecté ?
            if await page.locator("text=Log in").first.is_visible(timeout=2000):
                print("⚠️ Session expirée, reconnexion...")
                await browser.close()
                await login_and_save_session()
                return await send_prompt_to_ai(prompt, system_prompt)

            textarea = page.locator("textarea[placeholder*='Send'], textarea").first
            await textarea.fill(full_prompt)
            await page.wait_for_timeout(500)
            await textarea.press("Enter")
            await page.wait_for_timeout(15000)

            raw_result = await page.evaluate("""(userPrompt) => {
                const lineClamps = document.querySelectorAll('.line-clamp-1, [class*="line-clamp-1"]');
                let bestText = "";
                lineClamps.forEach(el => {
                    let parent = el.closest('div[class*="message"], article, section, div[class*="group"], div.relative');
                    if (!parent) parent = el.parentElement?.parentElement;
                    if (parent) {
                        let t = parent.innerText.trim();
                        if (t && !t.includes(userPrompt) && t.length > 5) bestText = t;
                    }
                });
                return bestText;
            }""", full_prompt)

            lines = raw_result.split("\n")
            filtered = [l.strip() for l in lines if l.strip() and "Response provided by" not in l
                        and l.strip() not in ["Max", "Google", "Claude", "GPT-4", "Gemini"]]
            return " ".join(filtered).strip() or "Aucune réponse détectée."
        finally:
            await context.close()
            await browser.close()
