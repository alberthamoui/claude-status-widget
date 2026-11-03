# Claude Status Widget

Um widget flutuante para Windows que mostra o que o Claude Code está fazendo:

| Estado | Visual | Quando |
|---|---|---|
| 🧠 **Pensando** | bolinha laranja pulsando + arco girando | prompt enviado, raciocínio, ferramentas rodando, subagentes, compactação |
| ⏳ **Aguardando você** | bolinha âmbar piscando com halo | pedido de permissão, `AskUserQuestion`, aprovação de plano, diálogos de MCP |
| 🟢 **Pronto** | bolinha verde fixa | o Claude terminou (`Stop`) ou você interrompeu com Esc |

## Arquitetura

```
Claude Code ──(hooks oficiais)──► hook.py ──► ~/.claude/claude-status-widget/sessions/<id>.json
                                                         ▲
                                         widget.py (Tkinter) lê a cada 400 ms
```

- **Captura:** pelos [hooks do Claude Code](https://docs.claude.com/en/docs/claude-code/hooks), a API de eventos oficial. Não depende de inspecionar DOM, rede ou tela, então não quebra quando a interface muda.
- **Ponte:** um arquivo JSON por sessão, gravado de forma atômica. Várias sessões ao mesmo tempo funcionam sem disputa de escrita.
- **Interface:** Python + Tkinter, que já vêm com o Python. Nenhum `pip install`.

| Evento do hook | Estado |
|---|---|
| `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SubagentStop`, `PreCompact` | thinking |
| `PermissionRequest`, `PreToolUse` de `AskUserQuestion`/`ExitPlanMode`, `Notification` do tipo `permission_prompt`/`elicitation_dialog` | waiting |
| `SessionStart`, `Stop`, `Notification` do tipo `idle_prompt` | idle |
| `SessionEnd` | remove a sessão |

O Esc não dispara nenhum hook. Por isso o widget olha o fim do transcript da sessão e, se encontrar `[Request interrupted by user`, mostra "Pronto".

Com várias sessões abertas, o widget mostra a mais urgente (aguardando > pensando > pronto) e um selo `+N`. O botão direito lista todas.

## Instalação

Requisitos: Python 3.8+ com Tkinter (o da Microsoft Store serve) e Claude Code.

1. Na pasta deste projeto, instale os hooks e copie os arquivos para `~/.claude/claude-status-widget/`:

   ```bash
   python install.py
   ```

   Para o widget abrir junto com o Windows, use `python install.py --startup`.

   O instalador faz backup do `settings.json` (`settings.json.bak-AAAAMMDD-HHMMSS`) e **mantém os hooks que você já tem**. Rodar de novo não duplica nada.

2. Abra o widget:

   ```bash
   pythonw "%USERPROFILE%\.claude\claude-status-widget\widget.py"
   ```

3. **Reinicie as sessões do Claude Code** que já estavam abertas. Os hooks só são carregados quando a sessão começa.

## Testando

- **Visual, sem o Claude:** `python widget.py --demo` alterna os 3 estados a cada 4 s.
- **Estados manuais, com o widget aberto:**

  ```bash
  python hook.py --test thinking
  python hook.py --test waiting
  python hook.py --test idle
  python hook.py --test clear
  ```

- **Com o Claude de verdade:** abra uma sessão nova e peça algo que rode um comando. O widget vai de *Pensando* para *Aguardando você* no pedido de permissão e termina em *Pronto*.

## Uso

- Arraste com o botão esquerdo para mover (a posição fica salva).
- Duplo clique alterna para o modo compacto (só a bolinha).
- O botão direito abre o menu: lista de sessões, **fixar na barra de tarefas**, sempre no topo, som ao aguardar você, limpar sessões antigas e sair.

### Modo barra de tarefas

O widget se encaixa no espaço livre à esquerda da barra, ao lado do clima. Ativa pelo menu ou com:

```bash
pythonw "%USERPROFILE%\.claude\claude-status-widget\widget.py" --taskbar
```

- Acompanha a altura da barra e o tema claro/escuro (o tema é lido quando o widget abre ou muda de modo).
- Arrastar move só na horizontal, ao longo da barra.
- Some quando um app está em tela cheia ou quando a barra se esconde sozinha.
- Para voltar a ser janela solta: desmarque no menu ou use `--floating`.

O Windows 11 não deixa colocar nada *dentro* da barra. O widget é uma janela sem borda, posicionada por cima dela, que volta para a frente a cada 250 ms (clicar na barra a traz para cima dele).

## Desinstalar

O instalador fica copiado junto com o widget, então dá para desinstalar de qualquer lugar:

```bash
python "%USERPROFILE%\.claude\claude-status-widget\install.py" --uninstall
```

## Limitações

- Cobre o **Claude Code**: CLI, extensão do VS Code e a aba Code do app desktop, que usam o `~/.claude/settings.json`. O chat do claude.ai no navegador não tem hooks. Para ele seria preciso uma extensão de navegador que observe o DOM, uma solução bem mais frágil.
- Depois que você aprova uma permissão, o estado só volta para *Pensando* quando a ferramenta termina (`PostToolUse`). Num comando longo, ele fica um tempo em *Aguardando você*.
- Se o Claude Code fechar abruptamente, sem `SessionEnd`, a sessão fica listada. Ela some sozinha após 8 h, ou na hora em "Limpar sessões antigas".
