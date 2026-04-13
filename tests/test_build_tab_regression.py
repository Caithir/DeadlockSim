"""Focused Build tab regression coverage."""

from playwright.sync_api import expect, sync_playwright


def test_build_tab_shows_metrics_large_slots_and_full_height_shop(gui_server):
    """Build tab should keep score metrics visible, use larger purchased slots, and size the shop near the viewport bottom."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto(gui_server)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        page.get_by_label("Sort By").click()
        page.wait_for_timeout(300)
        page.evaluate(
            """() => {
                for (const item of document.querySelectorAll('.q-item')) {
                    if (item.textContent && item.textContent.includes('★ Gun DPS Δ')) {
                        item.click();
                        return true;
                    }
                }
                return false;
            }"""
        )
        page.wait_for_timeout(1200)

        metrics = page.locator(".dl-score-metrics")
        expect(metrics.first).to_be_visible()
        assert metrics.locator(".dl-score-metric").count() > 0

        first_card = page.locator(".dl-card-wrapper").first
        expect(first_card).to_be_visible()
        first_card.click()

        filled_slot = page.locator(".bl-slot-filled").first
        expect(filled_slot).to_be_visible()
        slot_box = filled_slot.bounding_box()
        assert slot_box is not None
        assert slot_box["width"] >= 48
        assert slot_box["height"] >= 48

        shop_scroll = page.locator(".q-scrollarea.border-l.rounded-r").first
        expect(shop_scroll).to_be_visible()
        scroll_box = shop_scroll.bounding_box()
        assert scroll_box is not None

        viewport = page.viewport_size
        assert viewport is not None
        bottom_gap = viewport["height"] - (scroll_box["y"] + scroll_box["height"])
        assert 0 <= bottom_gap <= 40

        browser.close()