# Claude Status Widget

Uma bolinha na barra de tarefas do Windows que mostra, só de olhar, o que o Claude Code está fazendo:

| Bolinha | Significa |
|---|---|
| 🟠 **Laranja pulsando, com um arco girando** | Pensando: lendo, escrevendo ou rodando comandos |
| 🟡 **Âmbar piscando** | Esperando você: permissão, pergunta ou plano para aprovar |
| 🟢 **Verde fixo** | Pronto para o próximo pedido |
| ⚫ **Cinza** | Nenhuma sessão do Claude Code aberta |

Requisitos: Windows 10 ou 11, Python 3.8+ e Claude Code.

## Instalar (o jeito fácil)

Abra o Claude Code e mande:

> Instale o widget deste repositório: https://github.com/alberthamoui/claude-widget

O Claude vai baixar o projeto, mostrar o que vai mudar no seu PC e pedir sua confirmação antes de instalar.

## Instruções para o Claude

> Esta seção é para o assistente que estiver instalando. Siga os passos na ordem e confirme com o usuário antes dos passos marcados com **(confirmar)**.

1. **Confira o sistema.** O widget só funciona no Windows. Em outro sistema, avise o usuário e pare.
2. **Confira o Python:** `python -c "import sys, tkinter; print(sys.version)"`. Precisa ser 3.8+ e ter Tkinter.
   - Se faltar Python **(confirmar)**: `winget install -e --id Python.Python.3.12`, depois abra um terminal novo.
   - Use o mesmo comando (`python` ou `py`) que funcionou aqui nos passos seguintes.
3. **Baixe o repositório** **(confirmar a pasta)**, por exemplo em `%USERPROFILE%\claude-widget`:
   ```bash
   git clone https://github.com/alberthamoui/claude-widget.git "%USERPROFILE%\claude-widget"
   ```
   Se já existir, atualize com `git -C "%USERPROFILE%\claude-widget" pull`.
4. **Leia o `install.py` antes de rodar.** Ele é curto e diz no topo tudo o que altera.
5. **Instale** **(confirmar)**. Mostre ao usuário o que vai mudar: o `~/.claude/settings.json` ganha hooks, com backup antes. Pergunte também se ele quer que o widget abra junto com o Windows.
   ```bash
   python "%USERPROFILE%\claude-widget\install.py" --startup
   ```
   Sem abrir junto com o Windows: o mesmo comando sem `--startup`.
6. **Confira** se o instalador terminou com `Pronto.` e se a bolinha apareceu na barra, ao lado do clima ou do botão Iniciar.
7. **Avise o usuário:**
   - as sessões do Claude Code que já estavam abertas podem precisar ser reiniciadas;
   - os cliques funcionam em cima da bolinha: o botão direito abre o menu e o duplo clique mostra a versão com texto.

Se o `install.py` mostrar `Erro:`, ele não alterou nada. Mostre a mensagem ao usuário.

## Instalar manualmente

```bash
git clone https://github.com/alberthamoui/claude-widget.git
cd claude-widget
python install.py --startup
```

O instalador copia os arquivos para `~/.claude/claude-status-widget/`. Depois disso, a pasta clonada pode ser apagada.

## Atualizar

Baixe a versão nova e rode o instalador de novo. Ele fecha o widget antigo, troca os arquivos e abre o novo, sem duplicar os hooks:

```bash
git -C "%USERPROFILE%\claude-widget" pull
python "%USERPROFILE%\claude-widget\install.py" --startup
```

## Uso

Os cliques só funcionam em cima da bolinha.

- **Botão direito:** abre o menu.
  - Lista das sessões abertas, com estado, projeto e o que cada uma está fazendo.
  - **Fixar na barra de tarefas:** desmarcado, o widget vira uma janela solta que você pode pôr em qualquer lugar da tela.
  - **Som ao aguardar você:** toca um aviso quando o Claude começa a esperar você.
  - **Modo compacto / normal:** alterna entre só a bolinha e a versão com texto.
  - **Limpar sessões antigas:** tira da lista as sessões que já terminaram.
  - **Sair:** fecha o widget. Para reabrir: `pythonw "%USERPROFILE%\.claude\claude-status-widget\widget.py"`.
- **Duplo clique:** faz o mesmo que "Modo compacto / normal".
- **Arrastar:** move a bolinha ao longo da barra. A posição fica salva.

Com várias sessões abertas, a bolinha mostra a mais urgente: esperando você > pensando > pronto. Ela também some quando um vídeo ou jogo está em tela cheia.

## Desinstalar

```bash
python "%USERPROFILE%\.claude\claude-status-widget\install.py" --uninstall
```

Remove os hooks (mantendo os seus), a inicialização automática e a pasta do widget.

## Como funciona

```
Claude Code ──(hooks oficiais)──► hook.py ──► ~/.claude/claude-status-widget/sessions/<id>.json
                                                         ▲
                                         widget.py (Tkinter) lê a cada 400 ms
```

- **Captura:** pelos [hooks do Claude Code](https://docs.claude.com/en/docs/claude-code/hooks), o sistema oficial de eventos. Não depende de ler a tela nem o tráfego de rede.
- **Ponte:** um arquivo JSON por sessão, gravado de forma atômica.
- **Interface:** Python + Tkinter, que já vêm com o Python. Nenhum `pip install`.

| Evento do hook | Estado |
|---|---|
| `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SubagentStop`, `PreCompact` | pensando |
| `PermissionRequest`, `PreToolUse` de `AskUserQuestion`/`ExitPlanMode`, `Notification` do tipo `permission_prompt`/`elicitation_dialog` | esperando você |
| `SessionStart`, `Stop`, `Notification` do tipo `idle_prompt` | pronto |
| `SessionEnd` | remove a sessão |

O Esc não dispara nenhum hook. Por isso o widget olha as últimas linhas do transcript da sessão e, se encontrar `[Request interrupted by user`, mostra "Pronto".

Para testar sem o Claude: `python widget.py --demo` alterna os estados, e `python hook.py --test thinking|waiting|idle|clear` cria uma sessão de teste.

## Segurança

Veja [SECURITY.md](SECURITY.md): o que o widget lê e grava, o que ele nunca faz e como reportar um problema.

## Limitações

- Só Windows. Cobre o **Claude Code** (aba Code do app desktop, terminal e VS Code). Não cobre o chat do claude.ai, o app do celular nem sessões na nuvem.
- Depois que você aprova uma permissão, a bolinha só volta para laranja quando o comando aprovado termina.
- Se o Claude Code fechar abruptamente, a sessão continua na lista. Ela some sozinha após 8 h, ou na hora em "Limpar sessões antigas".
- Não funciona com `CLAUDE_CONFIG_DIR` apontando para outra pasta que não `~/.claude`.
