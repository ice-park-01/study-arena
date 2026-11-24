// 공부 타이머. 화면에 보이는 숫자는 편의용이고, 실제 시간은 서버가 계산한다.
(() => {
  const bar = document.getElementById("timerbar");
  if (!bar) return;
  const value = document.getElementById("timer-value");
  const state = document.getElementById("timer-state");
  const button = document.getElementById("timer-btn");
  const TICK_MS = 30000;
  let seconds = Number(bar.dataset.seconds) || 0;
  let syncedAt = Date.now();
  let running = false;
  try { running = localStorage.getItem("arena.running") === "1"; } catch (e) {}

  const visible = () => document.visibilityState === "visible";
  const format = (s) => {
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  };
  function render() {
    const active = running && visible();
    const shown = active ? seconds + Math.min(30, Math.floor((Date.now() - syncedAt) / 1000)) : seconds;
    value.textContent = format(shown);
    bar.classList.toggle("running", running);
    state.textContent = running ? "공부 중" : "쉬는 중";
    button.textContent = running ? "잠시 멈춤" : "공부 시작";
  }
  async function tick() {
    if (!running || !visible()) return;
    try {
      const res = await fetch("/api/tick", { method: "POST" });
      if (res.ok) {
        seconds = (await res.json()).today_seconds;
        syncedAt = Date.now();
      }
    } catch (e) { /* 네트워크가 끊기면 다음 신호에서 다시 시도한다 */ }
    render();
  }
  button.addEventListener("click", () => {
    running = !running;
    try { localStorage.setItem("arena.running", running ? "1" : "0"); } catch (e) {}
    syncedAt = Date.now();
    render();
    if (running) tick();
    else fetch("/api/pause", { method: "POST" }).catch(() => {});
  });
  document.addEventListener("visibilitychange", () => { syncedAt = Date.now(); tick(); });
  setInterval(tick, TICK_MS);
  setInterval(render, 1000);
  render();
  tick();
})();
