import {t} from "/static/i18n.js"
import {Chessboard, COLOR} from "/static/vendor/cm-chessboard/src/Chessboard.js"

const ASSETS = "/static/vendor/cm-chessboard/assets/"
const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
const ANIMATION_MS = 200
const colorFilter = document.getElementById("color-filter")
const speedFilter = document.getElementById("speed-filter")
const pathBox = document.getElementById("path")
const summary = document.getElementById("summary")
const table = document.getElementById("moves-table")
const tbody = document.getElementById("moves-body")
const empty = document.getElementById("empty")
const legend = document.getElementById("legend")
const prevButton = document.getElementById("prev")
const forwardButton = document.getElementById("forward")
let board = null
let color = "white"
let path = []
let forward = []
let current = {moves: []}

function selectedSpeeds() {
    return [...speedFilter.querySelectorAll("[aria-pressed=true]")].map((button) => button.dataset.speed)
}

function currentFen() {
    return path.length ? path[path.length - 1].fen : START
}

function percent(part, total) {
    return t("js.percent", {value: Math.round((100 * part) / total)})
}

function gamesLabel(count) {
    return t("js.games", {count})
}

async function fetchMoves() {
    const speeds = selectedSpeeds()
    if (speeds.length === 0) {
        return {mine: true, total: 0, moves: []}
    }
    const query = [`color=${color}`, `fen=${encodeURIComponent(currentFen())}`, ...speeds.map((s) => `speed=${s}`)]
    return (await fetch(`/api/repertoire/moves?${query.join("&")}`)).json()
}

function resultBar(move) {
    const bar = document.createElement("div")
    bar.className = "bar"
    for (const kind of ["win", "draw", "loss"]) {
        const part = document.createElement("span")
        part.className = kind
        part.style.width = percent(move[kind], move.games)
        bar.append(part)
    }
    const label = document.createElement("div")
    label.className = "bar-label"
    label.textContent = t("js.result", {win: move.win, draw: move.draw, loss: move.loss})
    const cell = document.createElement("td")
    cell.append(bar, label)
    return cell
}

function cell(text, className) {
    const td = document.createElement("td")
    td.textContent = text
    if (className) {
        td.className = className
    }
    return td
}

function tone(move, baseline) {
    const gap = (move.later_errors / move.games - baseline) * 100
    if (Math.abs(gap) < 1) {
        return "neutral"
    }
    return gap > 0 ? "above" : "below"
}

function moveRow(move, total, baseline) {
    const row = document.createElement("tr")
    row.className = `${move.mine ? "mine" : "theirs"} ${tone(move, baseline)}`
    const serious = `${percent(move.later_errors, move.games)} (${move.later_errors}/${move.games})`
    row.append(
        cell(move.san, "san"),
        cell(`${move.games} (${percent(move.games, total)})`, "share"),
        resultBar(move),
        cell(serious),
    )
    row.addEventListener("click", () => play(move))
    return row
}

function renderPath() {
    pathBox.replaceChildren()
    const start = document.createElement("button")
    start.type = "button"
    start.textContent = t("js.start_position")
    start.setAttribute("aria-current", path.length === 0 ? "true" : "false")
    start.addEventListener("click", () => goTo(0))
    pathBox.append(start)
    path.forEach((step, i) => {
        if (i % 2 === 0) {
            const number = document.createElement("span")
            number.className = "no"
            number.textContent = `${i / 2 + 1}.`
            pathBox.append(number)
        }
        const button = document.createElement("button")
        button.type = "button"
        button.textContent = step.san
        button.setAttribute("aria-current", i === path.length - 1 ? "true" : "false")
        button.addEventListener("click", () => goTo(i + 1))
        pathBox.append(button)
    })
}

function nextStep() {
    if (forward.length) {
        return forward[forward.length - 1]
    }
    return current.moves.length === 1 ? current.moves[0] : null
}

function updateNav() {
    prevButton.disabled = path.length === 0
    forwardButton.disabled = nextStep() === null
}

async function render() {
    renderPath()
    const data = await fetchMoves()
    current = data
    updateNav()
    const games = data.moves.reduce((sum, move) => sum + move.games, 0)
    const baseline = games ? data.moves.reduce((sum, move) => sum + move.later_errors, 0) / games : 0
    tbody.replaceChildren(...data.moves.map((move) => moveRow(move, data.total, baseline)))
    table.hidden = data.moves.length === 0
    legend.hidden = data.moves.length === 0
    empty.hidden = data.moves.length > 0
    if (selectedSpeeds().length === 0) {
        empty.textContent = t("js.pick_speed")
    } else {
        empty.textContent = path.length ? t("js.empty.path") : t("js.empty.none")
    }
    summary.textContent = data.total ? t("js.summary", {games: gamesLabel(data.total), turn: t(data.mine ? "js.turn.mine" : "js.turn.theirs")}) : ""
}

async function show() {
    await board.setPosition(currentFen(), true)
    await render()
}

function play(move) {
    const next = forward[forward.length - 1]
    forward = next && next.fen === move.fen ? forward.slice(0, -1) : []
    path.push({san: move.san, fen: move.fen})
    return show()
}

function goTo(length) {
    forward = [...forward, ...path.slice(length).reverse()]
    path = path.slice(0, length)
    return show()
}

function stepForward() {
    const step = nextStep()
    return step ? play(step) : undefined
}

function stepBack() {
    return path.length ? goTo(path.length - 1) : undefined
}

function boardColor() {
    return color === "white" ? COLOR.white : COLOR.black
}

colorFilter.addEventListener("click", (event) => {
    const button = event.target.closest("button")
    if (!button || button.dataset.color === color) {
        return
    }
    color = button.dataset.color
    colorFilter.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b === button ? "true" : "false"))
    path = []
    forward = []
    board.setOrientation(boardColor())
    show()
})
speedFilter.addEventListener("click", (event) => {
    const button = event.target.closest("button")
    if (button) {
        button.setAttribute("aria-pressed", button.getAttribute("aria-pressed") === "true" ? "false" : "true")
        render()
    }
})
prevButton.addEventListener("click", stepBack)
forwardButton.addEventListener("click", stepForward)
document.addEventListener("keydown", (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey) {
        return
    }
    const actions = {ArrowLeft: stepBack, ArrowRight: stepForward, Home: () => goTo(0)}
    if (event.key in actions) {
        event.preventDefault()
        actions[event.key]()
    }
})
board = new Chessboard(document.getElementById("board"), {
    position: START,
    orientation: boardColor(),
    assetsUrl: ASSETS,
    style: {animationDuration: ANIMATION_MS},
})
render()
