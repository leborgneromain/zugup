import {t, raw} from "/static/i18n.js"
import {Chessboard, COLOR, INPUT_EVENT_TYPE} from "/static/vendor/cm-chessboard/src/Chessboard.js"

const ASSETS = "/static/vendor/cm-chessboard/assets/"
const ANIMATION_MS = 200
const game = document.getElementById("game")
const info = document.getElementById("info")
const counter = document.getElementById("counter")
const speedFilter = document.getElementById("speed-filter")
const feedback = document.getElementById("feedback")
const nextButton = document.getElementById("next")
const replayButton = document.getElementById("replay")
const replayPanel = document.getElementById("replay-panel")
const replayPrev = document.getElementById("replay-prev")
const replayNext = document.getElementById("replay-next")
const replayLabel = document.getElementById("replay-label")
const training = document.getElementById("training")
const movesList = document.getElementById("moves")
let board = null
let exercise = null
let answering = false
let replay = null

function isPromotion(piece, squareTo) {
    return piece && piece[1] === "p" && (squareTo[1] === "8" || squareTo[1] === "1")
}

function playerLabel(player) {
    return player.elo ? `${player.name} (${player.elo})` : player.name
}

function translated(prefix, value) {
    const key = `js.${prefix}.${value}`
    return raw(key) === undefined ? value : t(key)
}

function infoLabel(exercise) {
    return t("js.info", {
        side: t(`js.side.${exercise.orientation}`),
        category: translated("category", exercise.category),
        phase: translated("phase", exercise.phase),
    })
}

const PLATFORMS = {lichess: "Lichess", chesscom: "Chess.com"}

function durationLabel(seconds) {
    if (seconds < 60) {
        return `${seconds}s`
    }
    const minutes = seconds / 60
    const text = Number.isInteger(minutes) ? `${minutes}` : minutes.toFixed(1)
    return minutes === 1 ? "1min" : `${text}mins`
}

function timeControlLabel(timeControl) {
    const match = /^(\d+)(?:\+(\d+))?$/.exec(timeControl || "")
    if (!match) {
        return timeControl || ""
    }
    const increment = Number(match[2] || 0)
    const base = durationLabel(Number(match[1]))
    return increment > 0 ? `${base} +${increment}s` : base
}

function cadenceLabel(exercise) {
    const speed = exercise.speed ? exercise.speed[0].toUpperCase() + exercise.speed.slice(1) : ""
    const time = timeControlLabel(exercise.time_control)
    if (speed && time) {
        return `${speed} (${time})`
    }
    return speed || time
}

function dateLabel(playedAt) {
    const date = new Date(playedAt)
    return t("js.date", {
        weekday: raw("js.days")[date.getUTCDay()],
        day: date.getUTCDate(),
        month: raw("js.months")[date.getUTCMonth()],
    })
}

function gameLabel(exercise) {
    const date = dateLabel(exercise.played_at)
    const platform = PLATFORMS[exercise.source] || exercise.source
    const when = [date, cadenceLabel(exercise)].filter(Boolean).join(" - ")
    return `${playerLabel(exercise.white)} vs ${playerLabel(exercise.black)}\n${when}\n${platform}`
}

function colorOf(exercise) {
    return exercise.orientation === "white" ? COLOR.white : COLOR.black
}

function setMoveInput(enabled) {
    if (board.isMoveInputEnabled()) {
        board.disableMoveInput()
    }
    if (enabled) {
        board.enableMoveInput(onInput, colorOf(exercise))
    }
}

function selectedSpeeds() {
    return [...speedFilter.querySelectorAll("[aria-pressed=true]")].map((button) => button.dataset.speed)
}

function counterLabel(remaining) {
    return t("js.exercises", {count: remaining})
}

async function fetchNext() {
    const speeds = selectedSpeeds()
    if (speeds.length === 0) {
        return {exercise: null, remaining: 0}
    }
    const query = speeds.map((speed) => `speed=${speed}`).join("&")
    return (await fetch(`/api/exercise/next?${query}`)).json()
}

async function loadNext() {
    await stopReplay()
    feedback.textContent = ""
    nextButton.hidden = true
    const data = await fetchNext()
    exercise = data.exercise
    counter.textContent = counterLabel(data.remaining)
    if (!exercise) {
        game.textContent = ""
        info.textContent = selectedSpeeds().length === 0
            ? t("js.pick_speed")
            : t("js.none_left")
        if (board) {
            setMoveInput(false)
        }
        return
    }
    game.textContent = gameLabel(exercise)
    info.textContent = infoLabel(exercise)
    if (!board) {
        board = new Chessboard(document.getElementById("board"), {
            position: exercise.fen,
            orientation: colorOf(exercise),
            assetsUrl: ASSETS,
            style: {animationDuration: ANIMATION_MS},
        })
    } else {
        await board.setPosition(exercise.fen)
        await board.setOrientation(colorOf(exercise))
    }
    answering = false
    setMoveInput(true)
}

async function submit(uci) {
    const response = await fetch(`/api/exercise/${exercise.move_id}/answer`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({move: uci}),
    })
    const data = await response.json()
    if (!response.ok) {
        feedback.textContent = t("js.move_rejected")
        await board.setPosition(exercise.fen, true)
        answering = false
        return
    }
    setMoveInput(false)
    const parts = [data.correct ? t("js.correct") : t("js.incorrect")]
    if (data.verdict === "equivalent") {
        parts.push(t("js.equivalent", {san: data.best_san}))
    } else if (!data.correct) {
        parts.push(t("js.reference", {san: data.best_san}))
    }
    if (data.message) {
        parts.push(data.message)
    }
    feedback.textContent = parts.join(" ")
    nextButton.hidden = false
}

function onInput(event) {
    if (event.type === INPUT_EVENT_TYPE.moveInputStarted) {
        return !answering
    }
    if (event.type === INPUT_EVENT_TYPE.validateMoveInput) {
        if (answering) {
            return false
        }
        answering = true
        const promotion = isPromotion(board.getPiece(event.squareFrom), event.squareTo) ? "q" : ""
        submit(event.squareFrom + event.squareTo + promotion)
        return true
    }
}

function buildMoveList() {
    movesList.replaceChildren()
    replay.sans.forEach((san, i) => {
        if (i % 2 === 0) {
            const row = document.createElement("li")
            const number = document.createElement("span")
            number.className = "no"
            number.textContent = `${i / 2 + 1}.`
            row.append(number)
            movesList.append(row)
        }
        const button = document.createElement("button")
        button.type = "button"
        button.textContent = san
        button.addEventListener("click", () => goToReplay(i + 1))
        movesList.lastElementChild.append(button)
    })
}

function markCurrentMove() {
    movesList.querySelectorAll("button").forEach((button, i) => {
        const current = i + 1 === replay.index
        button.setAttribute("aria-current", current ? "true" : "false")
        if (current) {
            const top = button.offsetTop
            const bottom = top + button.offsetHeight
            if (top < movesList.scrollTop) {
                movesList.scrollTop = top
            } else if (bottom > movesList.scrollTop + movesList.clientHeight) {
                movesList.scrollTop = bottom - movesList.clientHeight
            }
        }
    })
}

function showReplayStep() {
    markCurrentMove()
    const last = replay.positions.length - 1
    const played = replay.index === 0 ? t("js.replay.start") : `${Math.ceil(replay.index / 2)}${replay.index % 2 ? "." : "..."} ${replay.sans[replay.index - 1]}`
    replayLabel.textContent = replay.index === last ? t("js.replay.position", {played}) : played
    replayPrev.disabled = replay.index === 0
    replayNext.disabled = replay.index === last
    return board.setPosition(replay.positions[replay.index], true)
}

async function startReplay() {
    const response = await fetch(`/api/exercise/${exercise.move_id}/history`)
    if (!response.ok) {
        return
    }
    const data = await response.json()
    setMoveInput(false)
    replay = {...data, index: data.positions.length - 1}
    replayButton.setAttribute("aria-pressed", "true")
    buildMoveList()
    replayPanel.hidden = false
    training.classList.add("replaying")
    await showReplayStep()
}

async function stopReplay() {
    if (!replay) {
        return
    }
    replay = null
    replayButton.setAttribute("aria-pressed", "false")
    replayPanel.hidden = true
    training.classList.remove("replaying")
    await board.setPosition(exercise.fen)
    setMoveInput(!answering)
}

async function goToReplay(index) {
    if (index >= 0 && index < replay.positions.length) {
        replay.index = index
        await showReplayStep()
    }
}

function stepReplay(delta) {
    return goToReplay(replay.index + delta)
}

replayButton.addEventListener("click", () => {
    if (replay) {
        stopReplay()
    } else if (exercise) {
        startReplay()
    }
})
replayPrev.addEventListener("click", () => stepReplay(-1))
replayNext.addEventListener("click", () => stepReplay(1))
document.addEventListener("keydown", (event) => {
    if (!replay || event.altKey || event.ctrlKey || event.metaKey) {
        return
    }
    const steps = {ArrowLeft: -1, ArrowRight: 1}
    if (event.key in steps) {
        event.preventDefault()
        stepReplay(steps[event.key])
    } else if (event.key === "Home" || event.key === "End") {
        event.preventDefault()
        goToReplay(event.key === "Home" ? 0 : replay.positions.length - 1)
    }
})
nextButton.addEventListener("click", loadNext)
speedFilter.addEventListener("click", (event) => {
    const button = event.target.closest("button")
    if (button) {
        button.setAttribute("aria-pressed", button.getAttribute("aria-pressed") === "true" ? "false" : "true")
        loadNext()
    }
})
loadNext()
