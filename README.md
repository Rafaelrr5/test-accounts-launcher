# Contas de teste em um clique

Abre uma janela anônima do Chrome para cada conta de teste de um sistema web, **já logada** (usuário, senha e código 2FA), com o nome da conta no título da janela. Serve para testar fluxo, permissão e tela com vários usuários ao mesmo tempo, sem ficar fazendo logout/login nem abrindo o app autenticador.

Também gera uma página local com login, senha e o código 2FA ao vivo de cada conta, para quando você precisa digitar à mão.

Funciona no **Windows, macOS e Linux**, com sistemas que têm uma página de login própria (usuário + senha, com ou sem 2FA por app autenticador). Não cobre login por Google/Microsoft (SSO) nem 2FA por SMS/e-mail.

## O que você precisa

- Google Chrome (no Linux também serve o Chromium)
- Python 3.9 ou mais novo
  - Windows: [python.org](https://www.python.org/downloads/), marcando **"Add python.exe to PATH"** na instalação
  - macOS: o que já vem com as ferramentas de desenvolvedor da Apple serve; se o Mac oferecer instalá-las na primeira vez, aceite. Ou instale pelo [python.org](https://www.python.org/downloads/)
  - Linux: o do sistema serve; no Ubuntu/Debian instale também o venv: `sudo apt install python3-venv`
- As contas de teste (login e senha). Se elas já têm 2FA ativo, a **chave** do 2FA de cada uma (o texto que aparece junto do QR code na ativação). Se ainda não têm, a ferramenta ativa para você (veja "Contas sem 2FA").

## Instalação (uma vez)

1. Baixe este repositório (**Code > Download ZIP**) e extraia numa pasta **fora** do OneDrive/iCloud/Google Drive (ex.: `C:\ferramentas\contas-teste` ou `~/ferramentas/contas-teste`). A configuração guarda senhas e não deve ir para a nuvem.
2. Rode o instalador:
   - **Windows:** dois cliques em **`instalar.bat`**
   - **macOS/Linux:** abra o Terminal na pasta e rode `bash instalar.sh`

   Ele:
   - cria um ambiente Python só desta ferramenta e instala a única dependência;
   - pergunta o endereço da página de login (copie da barra do navegador, ex.: `https://app.suaempresa.com/login`);
   - pergunta as contas, uma por vez: login, senha, nome que a janela vai mostrar e a chave 2FA (Enter se não tiver);
   - cria os dois atalhos.

Se algo falhar, a mensagem diz o quê; corrija e rode o instalador de novo (o que já foi feito é mantido).

## Uso no dia a dia

| Atalho | O que faz |
|---|---|
| **Contas de teste** | Abre uma janela por conta e faz o login. Janela que já está aberta é reaproveitada (se a sessão caiu, ele loga de novo). Leva uns 20-40 s por conta. |
| **Senhas e códigos 2FA** | Abre uma página local com login, senha (botão copiar) e o código 2FA atualizado a cada 30 s. |

Onde os atalhos aparecem:

- **Windows:** na área de trabalho.
- **macOS:** na Mesa (`Contas de teste.app`). Pode arrastar para o Dock.
- **Linux:** no menu de aplicativos e, se existir, na pasta Área de Trabalho. No Ubuntu, se o ícone da área de trabalho pedir, clique com o botão direito > "Permitir execução".

Pela linha de comando, dentro da pasta (Windows: `.venv\Scripts\python.exe`; macOS/Linux: `.venv/bin/python`):

```
python launcher.py setup             adicionar/atualizar contas ou trocar o endereço
python launcher.py open              abrir e logar as janelas
python launcher.py page              página de senhas e códigos 2FA
python launcher.py enroll <conta>    ativar 2FA de uma conta (login, nome ou número)
python launcher.py shortcut          recriar os atalhos
```

## Contas sem 2FA

Se o sistema exige 2FA e a conta nunca ativou, rode (troque `python` pelo Python do ambiente, como acima):

```
python launcher.py enroll "login.da.conta"
```

Ele abre a janela da conta, faz o login, passa pelas telas de ativação, **guarda a chave** que a tela mostra, confirma com o primeiro código e guarda os códigos de recuperação. Se alguma tela tiver um botão que ele não conhece, ele espera: clique você e ele continua de onde parou.

Se a conta **já tem 2FA** mas você não tem a chave, não dá para recuperá-la: peça a quem administra o sistema para resetar o 2FA da conta e rode o `enroll`.

## Mais de um ambiente (desenvolvimento, homologação...)

Cada ambiente tem o seu arquivo de configuração e suas portas:

```
python launcher.py --config hom.json setup
python launcher.py --config hom.json shortcut
```

No `hom.json`, troque `"base_port"` para outra faixa (ex.: `9441`) para as janelas dos dois ambientes não se misturarem. Os atalhos saem com o nome do arquivo no fim, ex.: "Contas de teste (hom)".

## Onde ficam as coisas

- `config.json`: endereço, contas, senhas e chaves 2FA. **Só no seu computador**, nunca vai para o Git (`.gitignore`). Para remover uma conta, apague o bloco dela nesse arquivo. Modelo em `example-config.json`.
- `profiles/`: perfis temporários do Chrome, um por conta.
- `contas.html`: a página de senhas, regenerada a cada clique no atalho.
- `run.log`: o que aconteceu no último clique do atalho (útil quando uma janela não loga).

## Problemas comuns

- **Janela parada em "Um momento..." ou "Verificando"**: é a verificação anti-robô do site (Cloudflare). Ela passa sozinha em janela visível; deixe a janela aberta e na tela. A ferramenta espera até 3 min por conta.
- **Uma conta "FALHOU" no `run.log`**: confira a senha com `setup`, ou se a conta pede 2FA e está sem chave (o log diz).
- **Código 2FA recusado sempre**: o relógio do computador precisa estar certo (acerte a hora automática nas configurações do sistema).
- **Botão de entrar com outro nome**: a ferramenta reconhece Entrar, Acessar, Sign in, Log in e Login; se o seu sistema usa outro texto, acrescente em `LOGIN_BUTTONS` no `launcher.py`.
- **"Chrome não encontrado"**: coloque o caminho do Chrome em `"chrome"` no `config.json`.

## Segurança

- Senhas e chaves 2FA ficam em texto no `config.json` da sua máquina. Use só para **contas de teste**, nunca para a sua conta pessoal ou de produção.
- As janelas aceitam controle apenas de programas do próprio computador (porta local), não de sites.

## Testes

- `python -m unittest discover -s tests`: testes rápidos.
- A cada envio ao GitHub, o fluxo `e2e` instala do zero no Windows, macOS e Linux exatamente como descrito acima, ativa o 2FA de uma conta, clica no atalho e confere que todas as janelas ficaram logadas. O site usado é um simulado local (`tests/mock_app.py`), sem nenhuma conta real.
