# 🎯 Marktplaats Hunter

> Автоматичний скаутинг ігрових ноутбуків RTX 4050/4060 для перепродажу.  
> Знаходить недооцінені оголошення, розраховує прибуток, надсилає алерти в Telegram.

---

## ⚡ Що робить система

| Компонент | Функція |
|-----------|---------|
| **Scraper** | Парсить Marktplaats кожні 45 сек через офіційний API |
| **Deal Engine** | Фільтрує, оцінює profit/risk/liquidity |
| **Database** | SQLite з дедуплікацією |
| **API** | FastAPI `/deals`, `/latest`, `/health` |
| **Telegram Bot** | Алерти лише для вигідних угод |
| **Mini App** | Telegram Web App для перегляду угод |

---

## 🚀 Швидкий старт

### 1. Клонування та налаштування

```bash
git clone <repo>
cd marktplaats-hunter
cp .env.example .env
# заповни .env своїми даними
```

### 2. Локальний запуск

```bash
pip install -r requirements.txt
cd app
python main.py
```

API буде доступне на `http://localhost:8000`  
Mini App: `http://localhost:8000/app`

### 3. Docker

```bash
docker build -t marktplaats-hunter .
docker run -p 8000:8000 --env-file .env marktplaats-hunter
```

---

## ☁️ Деплой на Railway

### Крок 1 — Створи проект

1. Зайди на [railway.app](https://railway.app)
2. **New Project → Deploy from GitHub** (підключи репозиторій)
3. Railway автоматично знайде `Dockerfile`

### Крок 2 — Налаштуй змінні середовища

У Railway dashboard → твій сервіс → **Variables**:

```
TELEGRAM_BOT_TOKEN   = токен від @BotFather
TELEGRAM_CHAT_ID     = твій chat ID (дізнайся через @userinfobot)
BASE_URL             = https://твій-app.railway.app
SCRAPE_INTERVAL      = 45
```

### Крок 3 — Деплой

```bash
railway up
```

або просто зроби push в GitHub — Railway задеплоїть автоматично.

### Крок 4 — Налаштуй Telegram Mini App

1. Відкрий @BotFather у Telegram
2. `/newapp` → обери свого бота
3. **Web App URL**: `https://твій-app.railway.app/app`
4. Готово! Кнопка "Mini App" у алертах запустить додаток

---

## 📱 Telegram Bot

Отримай chat ID:
1. Напиши `/start` своєму боту
2. Відкрий `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Знайди `"chat":{"id":XXXXXXXXX}` — це твій `TELEGRAM_CHAT_ID`

---

## 🔌 API Endpoints

| Метод | Шлях | Опис |
|-------|------|------|
| GET | `/health` | Статус + статистика |
| GET | `/deals` | Список вигідних угод |
| GET | `/latest` | Останні оголошення |
| GET | `/deals/{id}` | Конкретна угода |
| GET | `/app` | Telegram Mini App |
| GET | `/docs` | Swagger UI |

### Параметри `/deals`

```
?sort_by=score|profit|newest|price
&min_profit=150
&gpu=RTX+4060
&max_price=900
&limit=50
&offset=0
```

---

## 🧠 Логіка вигідності

```
Ринкові ціни:
  RTX 4050 → market €1000, resale €950
  RTX 4060 → market €1150, resale €1100

Угода вигідна якщо:
  discount ≥ 20% від ринкової ціни
  AND profit ≥ €150

Deal Score (0–100):
  + profit / 10     (max 40 pts)
  + discount * 0.8  (max 30 pts)
  + liquidity bonus (0/10/20)
  − risk penalty    (0/5/15)
```

### Ліквідність

| Рівень | Бренди |
|--------|--------|
| High | ASUS TUF, Lenovo LOQ, HP Victus, MSI, ASUS ROG |
| Medium | Dell G15, Acer Nitro, Gigabyte, Samsung |
| Low | Решта |

### Ризик

| Рівень | Критерії |
|--------|---------|
| Low | довгий опис, досвідчений продавець, знижка < 35% |
| Medium | короткий опис або новий продавець |
| High | знижка > 45%, мінімальний опис, новий акаунт |

---

## 📁 Структура проекту

```
marktplaats-hunter/
├── app/
│   ├── main.py          # Entrypoint (API + Worker)
│   ├── api.py           # FastAPI routes
│   ├── worker.py        # Background scrape loop
│   ├── scraper.py       # Marktplaats parser
│   ├── deal_engine.py   # Profit/risk logic
│   ├── database.py      # SQLite layer
│   └── telegram_bot.py  # Alert sender
├── frontend/
│   └── index.html       # Telegram Mini App
├── data/                # SQLite DB (auto-created)
├── Dockerfile
├── railway.toml
├── requirements.txt
└── .env.example
```

---

## 💡 Поради

- **Перший запуск**: перші алерти прийдуть після першого циклу (~1 хв)
- **Railway sleep**: використовуй платний план щоб сервіс не засинав
- **Багато алертів**: збільш `MIN_DISCOUNT_PCT` або `MIN_PROFIT_EUR` в `deal_engine.py`
- **Немає угод**: ринок може бути спокійним — перевір `/latest` щоб бачити що скрапується

---

## ⚠️ Disclaimer

Система для особистого використання. Дотримуйся Terms of Service Marktplaats.  
Не зловживай частотою запитів.
