# Segurança

O widget roda dentro do seu Claude Code (os hooks são chamados a cada ação do Claude). Por isso ele foi feito para ser pequeno, fácil de auditar e incapaz de atrapalhar o Claude.

## O que ele faz

| | |
|---|---|
| **Grava** | `~/.claude/claude-status-widget/`: a cópia dos arquivos, um JSON por sessão e a configuração do widget. Também acrescenta os próprios hooks ao `~/.claude/settings.json`, com backup antes, e, só com `--startup`, cria `ClaudeStatusWidget.vbs` na pasta Inicializar do Windows. |
| **Lê** | O JSON que o Claude Code entrega ao hook e, para detectar o Esc, as últimas ~6 KB do transcript da sessão (apenas arquivos `.jsonl` dentro de `~/.claude`). |
| **Guarda de cada sessão** | Estado, nome da ferramenta (ex.: `Bash`), pasta do projeto, caminho do transcript, horários e o início do texto de notificações do Claude Code (ex.: "Claude needs your permission to use Bash"). |

## O que ele nunca faz

- **Rede:** não acessa a internet nem nenhum servidor. O único socket é uma trava em `127.0.0.1` para não abrir dois widgets; ele nunca aceita conexões.
- **Conteúdo:** não guarda prompts, respostas, comandos nem conteúdo de arquivos. O `tool_input` dos hooks é ignorado.
- **Dependências:** não instala nada. É só a biblioteca padrão do Python, então não há pacote de terceiros para ser comprometido.
- **Atrapalhar o Claude:** o hook nunca imprime nada (em alguns eventos isso viraria contexto do modelo), sempre sai com código 0 (nunca bloqueia uma ação), tem timeout de 5 s e ignora qualquer erro.
- **Mexer em outros hooks:** os hooks que já existem no `settings.json` são preservados. A desinstalação remove só as entradas que contêm `claude-status-widget`.

## Proteções contra dados forjados

- O `session_id` só é aceito se tiver letras, números, `-` e `_`. Assim, um id como `../../x` não consegue gravar nem apagar arquivos fora da pasta do widget.
- O widget valida o tipo de cada campo dos JSONs de sessão e ignora arquivos malformados em vez de travar.
- "Limpar sessões antigas" só apaga arquivos listados dentro da pasta `sessions/`.
- O `settings.json` é gravado num arquivo temporário e trocado de uma vez. Um erro no meio da gravação não corrompe a configuração do Claude. Se ele estiver inválido, o instalador para sem alterar nada.
- A desinstalação só remove a pasta `~/.claude/claude-status-widget`.

## Antes de instalar

São três arquivos Python curtos (`hook.py`, `install.py`, `widget.py`). Leia-os ou peça ao seu Claude para ler antes de rodar. O instalador mostra o commit que está sendo instalado.

## Reportar um problema

Encontrou uma falha de segurança? Use **Security → Report a vulnerability** no GitHub do repositório, de forma privada, em vez de abrir uma issue pública.
