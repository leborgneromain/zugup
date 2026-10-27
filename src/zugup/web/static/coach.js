const list = document.querySelector(".tasks")

async function toggle(box) {
    const response = await fetch("/api/coach/check", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({speed: list.dataset.speed, task: box.dataset.task, done: box.checked}),
    })
    if (!response.ok) {
        box.checked = !box.checked
        return
    }
    box.closest(".task").classList.toggle("done", box.checked)
}

if (list) {
    list.addEventListener("change", (event) => {
        if (event.target.matches("input[type=checkbox]")) {
            toggle(event.target)
        }
    })
}
