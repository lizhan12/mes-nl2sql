import puppeteer from "puppeteer";
import { mkdirSync, writeFileSync } from "fs";
import { join } from "path";

const SCREENSHOT_DIR = join(import.meta.dirname, "test-screenshots");
const BASE_URL = "http://localhost:8000/console/knowledge";

const logs = [];
let stepNum = 0;

function log(msg) {
  const line = `[Step ${stepNum}] ${msg}`;
  console.log(line);
  logs.push(line);
}

async function screenshot(page, name) {
  const path = join(SCREENSHOT_DIR, `${name}.png`);
  await page.screenshot({ path, fullPage: false });
  log(`Screenshot saved: ${name}.png`);
  return path;
}

async function dumpConsole(page) {
  const msgs = await page.evaluate(() => {
    return window.__testErrors || [];
  });
  if (msgs.length > 0) {
    log(`Browser console errors: ${JSON.stringify(msgs)}`);
  }
  // Clear
  await page.evaluate(() => { window.__testErrors = []; });
}

async function run() {
  mkdirSync(SCREENSHOT_DIR, { recursive: true });

  const browser = await puppeteer.launch({
    headless: "new",
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });

  // Collect console errors
  await page.evaluateOnNewDocument(() => {
    window.__testErrors = [];
    const origError = console.error;
    console.error = (...args) => {
      window.__testErrors.push(args.map(String).join(" "));
      origError.apply(console, args);
    };
  });

  // ── Step 1: Navigate ──
  stepNum = 1;
  log(`Navigating to ${BASE_URL}...`);
  await page.goto(BASE_URL, { waitUntil: "networkidle2", timeout: 15000 });
  log("Page loaded.");

  // ── Step 2: Wait for data to load ──
  stepNum = 2;
  log("Waiting 3 seconds for data to load...");
  await new Promise((r) => setTimeout(r, 3000));
  log("Wait complete.");
  await dumpConsole(page);

  // ── Step 3: Screenshot 01 ──
  stepNum = 3;
  await screenshot(page, "01-page-loaded");

  // ── Step 4: Click a table in the left sidebar ──
  stepNum = 4;
  log("Looking for table items in the left sidebar...");

  // The sidebar is the <aside> element, table items are <li> with monospace font
  const tableItems = await page.$$("aside ul li");
  log(`Found ${tableItems.length} table items in sidebar.`);

  if (tableItems.length > 0) {
    // Click the first table
    const tableName = await page.evaluate(
      (el) => el.querySelector("span")?.textContent || "unknown",
      tableItems[0]
    );
    log(`Clicking first table: "${tableName}"`);
    await tableItems[0].click();
    log("Clicked. Waiting 1 second for detail to load...");
    await new Promise((r) => setTimeout(r, 1000));
  } else {
    log("WARNING: No table items found! Trying alternative selector...");
    // Try clicking any clickable element in the sidebar
    const sidebarLinks = await page.$$("aside li, aside [role='button'], aside .cursor-pointer");
    log(`Found ${sidebarLinks.length} clickable elements.`);
    if (sidebarLinks.length > 0) {
      await sidebarLinks[0].click();
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
  await dumpConsole(page);

  // ── Step 5: Screenshot 02 ──
  stepNum = 5;
  await screenshot(page, "02-table-selected");

  // ── Step 6: Find and click "添加关系" button ──
  stepNum = 6;
  log("Looking for '添加关系' button...");

  // Try multiple strategies to find the button
  let addRelationBtn = null;

  // Strategy 1: Find button containing "添加关系" text
  const buttons = await page.$$("button");
  for (const btn of buttons) {
    const text = await page.evaluate((el) => el.textContent?.trim() || "", btn);
    if (text.includes("添加关系")) {
      addRelationBtn = btn;
      log(`Found button with text: "${text}"`);
      break;
    }
  }

  if (addRelationBtn) {
    log("Clicking '添加关系' button...");
    await addRelationBtn.click();
    log("Clicked. Waiting 1 second for modal...");
    await new Promise((r) => setTimeout(r, 1000));
  } else {
    log("WARNING: '添加关系' button not found! Checking if page is in edit mode...");
    // Maybe we need to check if the edit mode is active
    const editBtns = await page.$$("button");
    for (const btn of editBtns) {
      const text = await page.evaluate((el) => el.textContent?.trim() || "", btn);
      log(`  Button: "${text}"`);
    }
  }
  await dumpConsole(page);

  // ── Step 7: Screenshot 03 ──
  stepNum = 7;
  await screenshot(page, "03-relation-modal");

  // ── Step 8: Click "目标表" SearchableSelect and type "test" ──
  stepNum = 8;
  log("Looking for '目标表' SearchableSelect input...");

  // The modal has: label > span("目标表") > SearchableSelect > input
  // SearchableSelect renders an input inside a div
  // The target table input has placeholder "搜索表名..."

  // Strategy: Find inputs inside the modal (z-50 fixed overlay)
  // The modal is the div with "fixed inset-0 z-50"
  // We need to find the input with placeholder "搜索表名..."

  let targetTableInput = null;

  // Find all inputs on page
  const allInputs = await page.$$("input");
  log(`Total inputs on page: ${allInputs.length}`);

  for (const inp of allInputs) {
    const placeholder = await page.evaluate((el) => el.placeholder || "", inp);
    const value = await page.evaluate((el) => el.value || "", inp);
    const visible = await page.evaluate((el) => {
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    }, inp);
    log(`  Input: placeholder="${placeholder}" value="${value}" visible=${visible}`);
  }

  // Find the input inside the modal with placeholder "搜索表名..."
  // The modal has a fixed overlay with z-50
  const modalInputs = await page.$$('div[class*="fixed"] input');
  for (const inp of modalInputs) {
    const placeholder = await page.evaluate((el) => el.placeholder || "", inp);
    if (placeholder.includes("搜索表名")) {
      targetTableInput = inp;
      log(`Found target table input with placeholder "${placeholder}"`);
      break;
    }
  }

  if (targetTableInput) {
    log("Clicking target table input...");
    await targetTableInput.click();
    await new Promise((r) => setTimeout(r, 300));

    // Check if it got focus
    const isFocused = await page.evaluate(
      (el) => document.activeElement === el,
      targetTableInput
    );
    log(`Input focused after click: ${isFocused}`);

    // Type "test"
    log('Typing "test"...');
    await targetTableInput.type("test", { delay: 80 });
    await new Promise((r) => setTimeout(r, 500));

    // Check value
    const inputValue = await page.evaluate((el) => el.value, targetTableInput);
    log(`Input value after typing: "${inputValue}"`);

    // Check if dropdown appeared (portal to body with zIndex 99999)
    const dropdownExists = await page.evaluate(() => {
      const portals = document.querySelectorAll('body > ul[class*="fixed"]');
      return portals.length;
    });
    log(`Dropdown portals found: ${dropdownExists}`);

    if (dropdownExists > 0) {
      const dropdownVisible = await page.evaluate(() => {
        const portal = document.querySelector('body > ul[class*="fixed"]');
        if (!portal) return false;
        const rect = portal.getBoundingClientRect();
        return { x: rect.x, y: rect.y, w: rect.width, h: rect.height, visible: rect.width > 0 && rect.height > 0 };
      });
      log(`Dropdown position: ${JSON.stringify(dropdownVisible)}`);
    }
  } else {
    log("WARNING: Could not find target table input. Looking for inputs near '目标表' text...");
    const targetLabels = await page.$$("span");
    for (const span of targetLabels) {
      const text = await page.evaluate((el) => el.textContent?.trim() || "", span);
      if (text === "目标表") {
        log("  Found '目标表' label span");
      }
    }
  }
  await dumpConsole(page);

  // ── Step 9: Screenshot 04 ──
  stepNum = 9;
  await screenshot(page, "04-typing-target-table");

  // ── Step 10: Click "源字段" or "目标字段" SearchableSelect and type ──
  stepNum = 10;
  log("Looking for field SearchableSelect inputs...");

  // Find inputs with placeholder "搜索字段..."
  let fieldInput = null;
  const fieldInputs = await page.$$('div[class*="fixed"] input');
  for (const inp of fieldInputs) {
    const placeholder = await page.evaluate((el) => el.placeholder || "", inp);
    if (placeholder.includes("搜索字段")) {
      fieldInput = inp;
      log(`Found field input with placeholder "${placeholder}"`);
      break;
    }
  }

  if (fieldInput) {
    log("Clicking field input...");
    await fieldInput.click();
    await new Promise((r) => setTimeout(r, 300));

    const isFocused = await page.evaluate(
      (el) => document.activeElement === el,
      fieldInput
    );
    log(`Field input focused after click: ${isFocused}`);

    log('Typing "id"...');
    await fieldInput.type("id", { delay: 80 });
    await new Promise((r) => setTimeout(r, 500));

    const inputValue = await page.evaluate((el) => el.value, fieldInput);
    log(`Field input value after typing: "${inputValue}"`);
  } else {
    log("WARNING: Could not find field input. Trying broader search...");
    const allInputs2 = await page.$$("input");
    for (const inp of allInputs2) {
      const placeholder = await page.evaluate((el) => el.placeholder || "", inp);
      if (placeholder) {
        log(`  Input placeholder: "${placeholder}"`);
      }
    }
  }
  await dumpConsole(page);

  // ── Step 11: Screenshot 05 ──
  stepNum = 11;
  await screenshot(page, "05-typing-field");

  // ── Final Summary ──
  stepNum = "FINAL";
  log("=== TEST COMPLETE ===");
  log(`Total screenshots saved in: ${SCREENSHOT_DIR}`);

  await browser.close();

  // Write logs
  writeFileSync(join(SCREENSHOT_DIR, "test-log.txt"), logs.join("\n"), "utf-8");
  console.log("\nLog saved to test-screenshots/test-log.txt");
}

run().catch((err) => {
  console.error("FATAL ERROR:", err);
  logs.push(`FATAL: ${err.message}`);
  writeFileSync(join(SCREENSHOT_DIR, "test-log.txt"), logs.join("\n"), "utf-8");
  process.exit(1);
});
