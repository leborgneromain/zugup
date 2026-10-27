import {t} from "/static/i18n.js"

const settingsStatus = document.getElementById("settings-status")
const speedsStatus = document.getElementById("speeds-status")
const resetStatus = document.getElementById("reset-status")
const group = document.getElementById("pref-speeds")
const accounts = document.getElementById("pref-accounts")
const importGroup = document.getElementById("pref-import-speeds")
const limit = document.getElementById("pref-limit")
const blocks = [...document.querySelectorAll(".account")]
const depthGroup = document.getElementById("pref-depth")
const themeGroup = document.getElementById("pref-theme")
const languageGroup = document.getElementById("pref-language")
const depthStatus = document.getElementById("depth-status")
const stockfishInput = document.getElementById("pref-stockfish")
const stockfishStatus = document.getElementById("stockfish-status")
const resetButton = document.getElementById("reset-button")
const STEPS = ["import_lichess", "import_chesscom", "classify"]
let timer = null

function put(body) {
    return fetch("/api/preferences", {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body),
    })
}

async function saveSpeeds(box) {
    const speeds = [...group.querySelectorAll("input:checked")].map((input) => input.value)
    if (speeds.length === 0) {
        box.checked = true
        speedsStatus.textContent = t("js.keep_speed")
        return
    }
    const response = await put({speeds})
    if (!response.ok) {
        box.checked = !box.checked
        speedsStatus.textContent = t("js.save_failed")
        return
    }
    speedsStatus.textContent = ""
}

async function saveDepth(choice) {
    const response = await put({depth: Number(choice.dataset.depth)})
    if (!response.ok) {
        depthStatus.textContent = t("js.save_failed")
        return
    }
    for (const option of depthGroup.querySelectorAll("button")) {
        option.setAttribute("aria-pressed", option === choice ? "true" : "false")
    }
    depthStatus.textContent = ""
}

async function saveStockfish() {
    const response = await put({stockfish_path: stockfishInput.value.trim()})
    if (!response.ok) {
        stockfishStatus.textContent = response.status === 400 ? t("js.stockfish_invalid") : t("js.save_failed")
        return
    }
    window.location.reload()
}

async function saveTheme(choice) {
    const response = await put({theme: choice.dataset.theme})
    if (!response.ok) {
        speedsStatus.textContent = t("js.save_failed")
        return
    }
    document.documentElement.dataset.theme = choice.dataset.theme
    for (const option of themeGroup.querySelectorAll("button")) {
        option.setAttribute("aria-pressed", option === choice ? "true" : "false")
    }
}

async function saveLanguage(choice) {
    const response = await put({language: choice.dataset.language})
    if (!response.ok) {
        speedsStatus.textContent = t("js.save_failed")
        return
    }
    window.location.reload()
}

async function saveAccounts(quiet = false) {
    const body = {
        accounts: {chesscom: accounts.elements.chesscom.value.trim()},
        import_limit: Number(limit.value),
    }
    const importSpeeds = [...importGroup.querySelectorAll("input:checked")].map((input) => input.value)
    if (importSpeeds.length === 0) {
        settingsStatus.textContent = t("js.keep_import_speed")
        return false
    }
    body.import_speeds = importSpeeds
    const response = await put(body)
    settingsStatus.textContent = response.ok ? (quiet === true ? "" : t("js.saved")) : t("js.invalid_settings")
    return response.ok
}

function describe(state) {
    if (state.state === "running") {
        const added = state.source === "resume" ? "" : t("js.sync.added", {count: state.added})
        if (state.step === "analyze") {
            return t("js.sync.analyzing", {analyzed: state.analyzed, total: state.total, added})
        }
        const step = STEPS.includes(state.step) ? state.step : "start"
        return `${t(`js.step.${step}`)}${added}`
    }
    if (state.state === "done") {
        const added = state.source === "resume" ? "" : t("js.sync.done_added", {count: state.added})
        return t("js.sync.done", {added, analyzed: state.analyzed})
    }
    if (state.state === "error") {
        return t("js.sync.error", {error: state.error})
    }
    return ""
}

function showBar(block, state, mine) {
    const bar = block.querySelector(".bar")
    const running = mine && state.state === "running"
    const importing = running && state.step !== "analyze"
    const percent = state.total > 0 ? Math.round((100 * state.analyzed) / state.total) : 100
    bar.hidden = !running
    bar.classList.toggle("indeterminate", importing)
    bar.firstElementChild.style.width = running && !importing ? `${percent}%` : ""
    if (running && !importing) {
        bar.setAttribute("aria-valuenow", percent)
    } else {
        bar.removeAttribute("aria-valuenow")
    }
}

function render(state, observed) {
    for (const block of blocks) {
        const mine = block.dataset.source === state.source
        showBar(block, state, mine)
        block.querySelector(".sync-status").textContent = mine && (observed || state.state === "running") ? describe(state) : ""
        const button = block.querySelector(".sync-button")
        if (button) {
            button.disabled = state.state === "running"
        }
        block.querySelector(".sync-refresh").hidden = !(mine && observed && (state.added > 0 || state.analyzed > 0))
    }
}

async function poll(observed) {
    const state = await (await fetch("/api/sync")).json()
    render(state, observed)
    if (state.state === "running") {
        timer = setTimeout(() => poll(true), 2000)
    }
}

async function startSync(block) {
    const status = block.querySelector(".sync-status")
    for (const button of document.querySelectorAll(".sync-button")) {
        button.disabled = true
    }
    const response = (await saveAccounts()) && await fetch("/api/sync", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({source: block.dataset.source}),
    })
    if (!response || !response.ok) {
        status.textContent = response && response.status === 400 ? t("js.need_username") : t("js.import_failed")
        render({state: "idle"}, false)
        return
    }
    clearTimeout(timer)
    poll(true)
}

async function resetData() {
    const games = Number(resetButton.dataset.games)
    const question = t("js.reset.confirm", {count: games})
    if (!window.confirm(question)) {
        return
    }
    const response = await fetch("/api/reset", {method: "POST"})
    if (response.ok) {
        window.location.reload()
        return
    }
    resetStatus.textContent = response.status === 409 ? t("js.reset.wait") : t("js.reset.failed")
}

group.addEventListener("change", (event) => saveSpeeds(event.target))
accounts.addEventListener("change", saveAccounts)
limit.addEventListener("change", saveAccounts)
importGroup.addEventListener("change", () => saveAccounts(true))
themeGroup.addEventListener("click", (event) => {
    const choice = event.target.closest("button")
    if (choice) {
        saveTheme(choice)
    }
})
languageGroup.addEventListener("click", (event) => {
    const choice = event.target.closest("button")
    if (choice && choice.getAttribute("aria-pressed") !== "true") {
        saveLanguage(choice)
    }
})
depthGroup.addEventListener("click", (event) => {
    const choice = event.target.closest("button")
    if (choice) {
        saveDepth(choice)
    }
})
resetButton.addEventListener("click", resetData)
if (stockfishInput) {
    stockfishInput.addEventListener("change", saveStockfish)
}
for (const block of blocks) {
    block.querySelector(".sync-button")?.addEventListener("click", () => startSync(block))
    block.querySelector(".sync-refresh").addEventListener("click", () => window.location.reload())
}
poll(false)

const disconnect = document.getElementById("lichess-disconnect")
if (disconnect) {
    disconnect.addEventListener("click", async () => {
        const response = await fetch("/api/lichess/disconnect", {method: "POST"})
        if (response.ok) {
            window.location.href = "/compte"
            return
        }
        disconnect.textContent = response.status === 409 ? t("js.disconnect.wait") : t("js.disconnect.failed")
    })
}

const quitButton = document.getElementById("quit-button")
if (quitButton) {
    quitButton.addEventListener("click", async () => {
        const response = await fetch("/api/quit", {method: "POST"})
        document.getElementById("quit-status").textContent = response.ok
            ? t("js.quit.done")
            : t("js.quit.failed")
    })
}
