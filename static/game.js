/* FitnessIT: конфетти, всплывающий XP, сундук, оплата. Без внешних библиотек. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var COLORS = ["#7c3aed", "#a78bfa", "#c084fc", "#ddd6fe", "#f2bf68", "#6dd5ac"];

  function confetti(n) {
    var fx = $("#fx");
    if (!fx || reduced) return;
    n = n || 140;
    for (var i = 0; i < n; i++) {
      var p = document.createElement("i");
      p.className = "confetti";
      p.style.left = Math.random() * 100 + "vw";
      p.style.background = COLORS[i % COLORS.length];
      p.style.animationDuration = 2.2 + Math.random() * 2.2 + "s";
      p.style.animationDelay = Math.random() * 0.6 + "s";
      p.style.setProperty("--rot", (Math.random() * 1440 - 720) + "deg");
      p.style.transform = "rotate(" + Math.random() * 360 + "deg)";
      if (Math.random() < 0.3) { p.style.borderRadius = "50%"; p.style.width = p.style.height = "9px"; }
      fx.appendChild(p);
      setTimeout(function (el) { el.remove(); }.bind(null, p), 5200);
    }
  }

  function floatXP(text, x, y) {
    var el = document.createElement("div");
    el.className = "xp-float";
    el.textContent = text;
    el.style.left = (x || window.innerWidth / 2) + "px";
    el.style.top = (y || window.innerHeight / 2) + "px";
    document.body.appendChild(el);
    setTimeout(function () { el.remove(); }, 1700);
  }

  function openModal(m) { if (m) m.classList.add("show"); }
  function closeModal(m) { if (m) m.classList.remove("show"); }

  // закрытие модалок
  document.addEventListener("click", function (e) {
    var close = e.target.closest("[data-close]");
    if (close) closeModal(close.closest(".modal"));
    else if (e.target.classList && e.target.classList.contains("modal")) closeModal(e.target);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") $$(".modal.show").forEach(closeModal);
  });

  // салют при новом уровне / успешной оплате
  $$("[data-confetti]").forEach(function () { setTimeout(function () { confetti(160); }, 250); });

  // флеш-сообщения с XP: всплывающее «+XP»
  $$(".flash[data-fx]").forEach(function (f) {
    var r = f.getBoundingClientRect();
    var m = f.textContent.match(/\+(\d+)\s*XP/);
    setTimeout(function () { floatXP(m ? "+" + m[1] + " XP" : "⭐", r.left + r.width / 2, r.top + 10); }, 200);
    if (f.dataset.fx === "levelup") confetti(90);
  });

  // полоски прогресса «заполняются» при загрузке
  if (!reduced) {
    $$(".meter i").forEach(function (bar) {
      var w = bar.style.width;
      bar.style.width = "0";
      requestAnimationFrame(function () { setTimeout(function () { bar.style.width = w; }, 60); });
    });
  }

  // ---------- сундук ----------
  var token = ($('meta[name="csrf-token"]') || {}).content;
  var busy = false;
  $$("[data-chest]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (busy) return;
      var modal = $("#chest-modal");
      if (!modal) return;
      if (btn.classList.contains("empty")) {
        $("[data-chest-title]", modal).textContent = "Сундук пуст";
        $("[data-chest-text]", modal).textContent = "Сегодня ты уже всё забрал. Новый сундук — завтра.";
        $("[data-chest-art]", modal).className = "chest-art";
        openModal(modal);
        return;
      }
      busy = true;
      var art = $("[data-chest-art]", modal);
      art.className = "chest-art shake";
      $("[data-chest-title]", modal).textContent = "Открываем…";
      $("[data-chest-kicker]", modal).textContent = "Ежедневный сундук";
      $("[data-chest-text]", modal).textContent = "Внутри случайный XP. Шанс на легендарный дроп — 5%.";
      openModal(modal);
      fetch("/chest", { method: "POST", headers: { "X-CSRFToken": token, "Accept": "application/json" }, credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          setTimeout(function () {
            busy = false;
            if (!d.ok) {
              art.className = "chest-art";
              $("[data-chest-title]", modal).textContent = "Упс";
              $("[data-chest-text]", modal).textContent = d.error || "Попробуй позже.";
              return;
            }
            var names = { common: "Обычный дроп", rare: "Редкий дроп! 💠", legendary: "ЛЕГЕНДАРНЫЙ ДРОП! 🌟" };
            art.className = "chest-art open " + d.rarity;
            art.querySelector(".chest-lid").textContent = d.rarity === "legendary" ? "🌟" : d.rarity === "rare" ? "💎" : "✨";
            $("[data-chest-kicker]", modal).textContent = names[d.rarity] || "Дроп";
            $("[data-chest-title]", modal).textContent = "+" + d.xp + " XP";
            $("[data-chest-text]", modal).textContent = d.levelup
              ? "Новый уровень: " + d.level + " · " + d.level_name + "! 🎉"
              : "Всего " + d.total + " XP. " + (d.left ? "Осталось сундуков: " + d.left + "." : "Следующий — завтра.");
            floatXP("+" + d.xp + " XP");
            confetti(d.rarity === "common" ? 60 : d.rarity === "rare" ? 120 : 220);
            // обновляем шапку без перезагрузки
            $$("[data-xp]").forEach(function (el) { el.textContent = d.total + " XP"; });
            $$("[data-xp-bar]").forEach(function (el) { el.style.width = d.pct + "%"; });
            $$(".lvl-n").forEach(function (el) { if (!el.closest(".hero-game")) el.textContent = d.level; });
            $$(".chest-btn").forEach(function (b) {
              var em = b.querySelector("em");
              if (d.left) { if (em) em.textContent = d.left; }
              else { b.classList.remove("ready"); b.classList.add("empty"); if (em) em.remove(); }
            });
            if (!d.left) $$(".chest-panel button[data-chest]").forEach(function (b) { b.disabled = true; b.textContent = "Завтра 🌙"; });
          }, reduced ? 0 : 900);
        })
        .catch(function () {
          busy = false;
          art.className = "chest-art";
          $("[data-chest-title]", modal).textContent = "Нет связи";
          $("[data-chest-text]", modal).textContent = "Не удалось открыть сундук. Обнови страницу.";
        });
    });
  });

  // ---------- тема ----------
  $$("[data-theme-toggle]").forEach(function (b) {
    b.addEventListener("click", function () {
      var root = document.documentElement;
      var cur = root.getAttribute("data-theme") ||
        (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      var next = cur === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("theme", next); } catch (e) {}
    });
  });

  // ---------- код из письма: 6 ячеек ----------
  var codeBox = $("[data-code-inputs]");
  if (codeBox) {
    var cells = $$("input", codeBox), hidden = $("[data-code-value]"), cform = $("[data-code-form]");
    hidden.name = "code";
    var sync = function () {
      hidden.value = cells.map(function (c) { return c.value; }).join("");
      cells.forEach(function (c) { c.classList.toggle("filled", !!c.value); });
      if (hidden.value.length === 6) { cform.requestSubmit ? cform.requestSubmit() : cform.submit(); }
    };
    var fill = function (from, digits) {
      for (var i = 0; i < digits.length && from + i < cells.length; i++) cells[from + i].value = digits[i];
      cells[Math.min(from + digits.length, cells.length - 1)].focus();
      sync();
    };
    cells.forEach(function (c, i) {
      c.addEventListener("input", function () {
        var d = c.value.replace(/\D/g, "");
        c.value = "";
        if (d) fill(i, d.split("")); else sync();
      });
      c.addEventListener("keydown", function (e) {
        if (e.key === "Backspace" && !c.value && i > 0) { cells[i - 1].value = ""; cells[i - 1].focus(); sync(); e.preventDefault(); }
        if (e.key === "ArrowLeft" && i > 0) cells[i - 1].focus();
        if (e.key === "ArrowRight" && i < cells.length - 1) cells[i + 1].focus();
      });
      c.addEventListener("paste", function (e) {
        var t = (e.clipboardData || window.clipboardData).getData("text").replace(/\D/g, "").slice(0, 6);
        if (t) { e.preventDefault(); fill(0, t.split("")); }
      });
      c.addEventListener("focus", function () { c.select(); });
    });
    if ($(".flash.error")) { codeBox.classList.add("shake"); }
  }
  var resend = $("[data-resend]");
  if (resend && +resend.dataset.wait > 0) {
    var left = +resend.dataset.wait;
    var tick = setInterval(function () {
      left -= 1;
      if (left <= 0) { clearInterval(tick); resend.disabled = false; resend.textContent = "Отправить код ещё раз"; }
      else resend.textContent = "Отправить снова через " + left + " с";
    }, 1000);
  }

  // ---------- оплата: живая карта ----------
  var card = $("[data-card]");
  if (card) {
    var num = $('[data-in="num"]'), holder = $('[data-in="holder"]'), exp = $('[data-in="exp"]'), cvc = $('[data-in="cvc"]');
    var show = function () {
      var digits = num.value.replace(/\D/g, "").slice(0, 19);
      num.value = digits.replace(/(.{4})/g, "$1 ").trim();
      var masked = (digits + "•".repeat(Math.max(0, 16 - digits.length))).replace(/(.{4})/g, "$1 ").trim();
      $("[data-card-num]").textContent = masked;
      $("[data-card-brand]").textContent = /^4/.test(digits) ? "VISA" : /^(5[1-5]|2[2-7])/.test(digits) ? "Mastercard" : "CARD";
    };
    num.addEventListener("input", show);
    holder.addEventListener("input", function () { $("[data-card-holder]").textContent = holder.value.toUpperCase() || "IVAN IVANOV"; });
    exp.addEventListener("input", function (e) {
      var d = exp.value.replace(/\D/g, "").slice(0, 4);
      if (d.length >= 3 || (d.length === 2 && e.inputType !== "deleteContentBackward")) d = d.slice(0, 2) + "/" + d.slice(2);
      exp.value = d;
      $("[data-card-exp]").textContent = d || "ММ/ГГ";
    });
    cvc.addEventListener("input", function () { cvc.value = cvc.value.replace(/\D/g, "").slice(0, 4); $("[data-card-cvc]").textContent = cvc.value.replace(/./g, "•") || "•••"; });
    cvc.addEventListener("focus", function () { card.classList.add("flip"); });
    cvc.addEventListener("blur", function () { card.classList.remove("flip"); });
  }
  $$(".pay-tabs .tab").forEach(function (t) {
    t.addEventListener("click", function () {
      $$(".pay-tabs .tab").forEach(function (x) { x.classList.toggle("on", x === t); });
      $$("[data-panel]").forEach(function (p) { p.hidden = p.dataset.panel !== t.dataset.tab; });
    });
  });
  $$(".pay-form").forEach(function (f) {
    f.addEventListener("submit", function () {
      var b = $("[data-pay-btn]", f);
      if (b) { b.classList.add("loading"); b.textContent = "Обработка платежа "; }
    });
  });
})();
