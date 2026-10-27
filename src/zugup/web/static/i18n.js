const messages = JSON.parse(document.getElementById("messages").textContent)

export function t(key, params = {}) {
    const count = params.count
    const plural = count === undefined ? null : `${key}.${count === 1 ? "one" : "other"}`
    const template = plural && plural in messages ? messages[plural] : messages[key]
    return template.replace(/\{(\w+)\}/g, (_, name) => params[name])
}

export function raw(key) {
    return messages[key]
}
