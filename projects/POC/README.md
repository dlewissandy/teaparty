# Getting Started — TeaParty POC

This guide walks you through running the TeaParty POC HTML dashboard on a fresh machine. No prior Python experience required.

---

## macOS

### 1. Install Git

Open **Terminal** (Applications → Utilities → Terminal) and run:

```shell
xcode-select --install
```

A dialog will appear. Click **Install** and wait for it to finish.

### 2. Install uv

[uv](https://docs.astral.sh/uv/) is the package manager used by this project. It also installs the correct Python version automatically — you do not need to install Python separately.

```shell
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart your terminal (or run `source ~/.zshrc`) so the `uv` command is available.

### 3. Clone the repository

```shell
git clone https://github.com/YOUR_ORG/teaparty.git  # replace with the actual repository URL
cd teaparty
```

### 4. Install dependencies

From the repo root:

```shell
uv sync
```

This installs all dependencies. If Python 3.12 or later is not already on your system, uv will download and install it automatically.

### 5. Run the dashboard

```shell
./teaparty.sh
```

Open http://localhost:8081 in your browser.

---

## Linux

### 1. Install Git

On Debian/Ubuntu:

```shell
sudo apt update && sudo apt install -y git
```

Other distributions use different package managers (e.g., `dnf` on Fedora, `pacman` on Arch). Install `git` with whatever your distro provides.

### 2. Install uv

```shell
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart your terminal (or run `source ~/.bashrc`) so the `uv` command is available.

### 3. Clone the repository

```shell
git clone https://github.com/YOUR_ORG/teaparty.git  # replace with the actual repository URL
cd teaparty
```

### 4. Install dependencies

From the repo root:

```shell
uv sync
```

This installs all dependencies. If Python 3.12 or later is not already on your system, uv will download and install it automatically.

### 5. Run the dashboard

```shell
./teaparty.sh
```

Open http://localhost:8081 in your browser.

---

## Windows

### Primary path: WSL2 (recommended)

WSL2 gives you a full Linux environment on Windows and is the easiest way to run the dashboard.

**1. Enable WSL2**

Open **PowerShell as Administrator** (right-click Start → Windows PowerShell (Admin)) and run:

```powershell
wsl --install
```

Restart your machine when prompted.

**2. Open Ubuntu**

After restarting, open the **Ubuntu** app from the Start menu. The first launch will ask you to create a username and password.

**3. Follow the Linux steps**

Inside the Ubuntu terminal, follow the [Linux](#linux) instructions above from step 1 (Install Git) through step 5 (Run the dashboard).

---

### Fallback: Git Bash / PowerShell (no WSL)

Use this if you cannot or do not want to set up WSL2.

**1. Install Git for Windows**

Download and install Git from [https://git-scm.com/download/win](https://git-scm.com/download/win). This also installs Git Bash.

**2. Install uv**

Open **PowerShell** and run:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen PowerShell so the `uv` command is available.

**3. Clone the repository**

```powershell
git clone https://github.com/YOUR_ORG/teaparty.git  # replace with the actual repository URL
cd teaparty
```

**4. Install dependencies**

```powershell
uv sync
```

**5. Run the dashboard**

```powershell
uv run python3 -m projects.POC.bridge
```

Open http://localhost:8081 in your browser.

---

## What to expect

After running the start command, a text-based terminal dashboard appears in your terminal window. You can navigate it with your keyboard.

---

## Further reading

Architecture and design documentation lives in [`projects/POC/docs/`](projects/POC/docs/).
