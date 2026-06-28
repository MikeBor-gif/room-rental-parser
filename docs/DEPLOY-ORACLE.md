# Деплой на Oracle Cloud (Always Free VM) — стабильная частота 24/7

В этом режиме парсер крутится постоянным процессом на бесплатной виртуальной
машине Oracle и проверяет Kufar каждые N секунд (точно, без задержек GitHub).
GitHub Actions при этом нужно **отключить**, чтобы не было дублей.

---

## Шаг 1. Создать аккаунт и VM (делаешь ты, в браузере)

1. Зарегистрируйся: https://www.oracle.com/cloud/free/
   - Нужна карта для верификации — **деньги не списываются**, тариф Always Free бесплатный.
2. В консоли Oracle: **Compute → Instances → Create instance**.
3. Параметры:
   - **Image:** Canonical Ubuntu (22.04 или 24.04).
   - **Shape:** из Always Free — `VM.Standard.A1.Flex` (ARM, до 4 OCPU / 24 ГБ)
     или `VM.Standard.E2.1.Micro` (AMD). Для нашей задачи хватит минимума.
   - **SSH keys:** нажми «Generate a key pair for me» и **скачай приватный ключ**
     (или вставь свой публичный ключ).
4. **Create** → дождись статуса Running → запиши **Public IP**.

> Сетевые порты открывать не нужно — парсер только исходящие запросы делает.

---

## Шаг 2. Подключиться к VM по SSH (ты)

```bash
# из папки со скачанным ключом
chmod 600 ssh-key.key
ssh -i ssh-key.key ubuntu@<PUBLIC_IP>
```

(В Windows можно через PowerShell тем же `ssh`, или через PuTTY.)

---

## Шаг 3. Установить и развернуть код (на VM)

```bash
# обновить систему и поставить python + git
sudo apt update
sudo apt install -y python3 python3-venv git

# клонировать репозиторий
sudo git clone https://github.com/MikeBor-gif/room-rental-parser.git /opt/room-rental-parser
sudo chown -R ubuntu:ubuntu /opt/room-rental-parser
cd /opt/room-rental-parser

# виртуальное окружение и зависимости
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

---

## Шаг 4. Настроить .env (на VM)

```bash
cp .env.example .env
nano .env
```

Заполни:

```
TELEGRAM_BOT_TOKEN=<токен от BotFather>
TELEGRAM_CHAT_ID=<твой chat_id>
LOG_LEVEL=INFO
POLL_INTERVAL_SECONDS=120     # проверять каждые 2 минуты (поставь нужное)
```

> `POLL_INTERVAL_SECONDS` > 0 включает режим демона (бесконечный цикл).
> Не ставь слишком маленькое значение (минимум разумно ~60 c), чтобы не нагружать Kufar.

Проверка вручную (один цикл, Ctrl+C для выхода):

```bash
./.venv/bin/python -m src.main
```

Должно появиться `Режим демона: интервал опроса 120 c` и далее прогоны.

---

## Шаг 5. Автозапуск через systemd (на VM)

```bash
sudo cp deploy/room-rental-parser.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now room-rental-parser
```

Проверка:

```bash
systemctl status room-rental-parser        # должно быть active (running)
journalctl -u room-rental-parser -f         # живой лог (Ctrl+C чтобы выйти)
```

Теперь сервис работает 24/7 и сам перезапускается при сбое/перезагрузке VM.

---

## Шаг 6. Отключить GitHub Actions (чтобы не было дублей)

После того как VM заработала — выключи облачное расписание одним из способов:

- **В вебе:** репозиторий → вкладка **Actions** → workflow **scrape** →
  кнопка `···` (справа) → **Disable workflow**.
- **Или** удали блок `schedule:` из `.github/workflows/scrape.yml`.

---

## Обновление кода в будущем (на VM)

```bash
cd /opt/room-rental-parser
git pull
./.venv/bin/pip install -r requirements.txt
sudo systemctl restart room-rental-parser
```

## Полезные команды

| Действие | Команда |
|---|---|
| Статус | `systemctl status room-rental-parser` |
| Живой лог | `journalctl -u room-rental-parser -f` |
| Перезапуск | `sudo systemctl restart room-rental-parser` |
| Остановить | `sudo systemctl stop room-rental-parser` |
| Поменять интервал | отредактировать `.env` → `sudo systemctl restart room-rental-parser` |
