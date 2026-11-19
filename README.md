# Contas de teste em um clique

Abre uma janela anônima do Chrome para cada conta de teste de um sistema web, **já logada** (usuário, senha e código 2FA), com o nome da conta no título da janela. Serve para testar fluxo, permissão e tela com vários usuários ao mesmo tempo, sem ficar fazendo logout/login nem abrindo o app autenticador.

Também gera uma página local com login, senha e o código 2FA ao vivo de cada conta, para quando você precisa digitar à mão.

Funciona com sistemas que têm uma página de login própria (usuário + senha, com ou sem 2FA por app autenticador). Não cobre login por Google/Microsoft (SSO) nem 2FA por SMS/e-mail.

## O que você precisa

- Windows 10/11 com Google Chrome
- Python 3.10 ou mais novo ([python.org](https://www.python.org/downloads/), marque **"Add python.exe to PATH"** na instalação)
- As contas de teste (login e senha). Se elas já têm 2FA ativo, a **chave** do 2FA de cada uma (o texto que aparece junto do QR code na ativação). Se ainda não têm, a ferramenta ativa para você (veja "Contas sem 2FA").

## Instalação (uma vez)

1. Baixe este repositório (**Code > Download ZIP**) e extraia numa pasta **fora** do OneDrive/Google Drive (ex.: `C:\ferramentas\contas-teste`). A configuração guarda senhas e não deve ir para a nuvem.
2. Dê dois cliques em **`instalar.bat`**. Ele:
   - cria um ambiente Python só desta ferramenta e instala a única dependência;
   - pergunta o endereço da página de login (copie da barra do navegador, ex.: `https://app.suaempresa.com/login`);
   - pergunta as contas, uma por vez: login, senha, nome que a janela vai mostrar e a chave 2FA (Enter se não tiver);
   - cria dois atalhos na área de trabalho.

Pronto. Se algo falhar, a mensagem diz o quê; corrija e rode `instalar.bat` de novo (o que já foi feito é mantido).

## Uso no dia a dia

| Atalho | O que faz |
|---|---|
| **Contas de teste** | Abre uma janela por conta e faz o login. Janela que já está aberta é reaproveitada (se a sessão caiu, ele loga de novo). Leva uns 20-40 s por conta. |
| **Senhas e códigos 2FA** | Abre uma página local com login, senha (botão copiar) e o código 2FA atualizado a cada 30 s. |

Pela linha de comando (dentro da pasta, com o Python do ambiente: `.venv\Scripts\python.exe`):

```
python launcher.py setup             adicionar/atualizar contas ou trocar o endereço
python launcher.py open              abrir e logar as janelas
python launcher.py page              página de senhas e códigos 2FA
python launcher.py enroll <conta>    ativar 2FA de uma conta (login, nome ou número)
python launcher.py shortcut          recriar os atalhos da área de trabalho
```

## Contas sem 2FA

Se o sistema exige 2FA e a conta nunca ativou, rode:

```
.venv\Scripts\python.exe launcher.py enroll "login.da.conta"
```

Ele abre a janela da conta, faz o login, passa pelas telas de ativação, **guarda a chave** que a tela mostra, confirma com o primeiro código e guarda os códigos de recuperação. Se alguma tela tiver um botão que ele não conhece, ele espera: clique você e ele continua de onde parou.

Se a conta **já tem 2FA** mas você não tem a chave, não dá para recuperá-la: peça a quem administra o sistema para resetar o 2FA da conta e rode o `enroll`.

## Mais de um ambiente (desenvolvimento, homologação...)

Cada ambiente tem o seu arquivo de configuração e suas portas:

```
.venv\Scripts\python.exe launcher.py --config hom.json setup
.venv\Scripts\python.exe launcher.py --config hom.json shortcut
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
- **Código 2FA recusado sempre**: o relógio do Windows precisa estar certo (Configurações > Hora > Sincronizar agora).
- **Botão de entrar com outro nome**: a ferramenta reconhece Entrar, Acessar, Sign in, Log in e Login; se o seu sistema usa outro texto, acrescente em `LOGIN_BUTTONS` no `launcher.py`.
- **"Chrome não encontrado"**: coloque o caminho do `chrome.exe` em `"chrome"` no `config.json`.

## Segurança

- Senhas e chaves 2FA ficam em texto no `config.json` da sua máquina. Use só para **contas de teste**, nunca para a sua conta pessoal ou de produção.
- As janelas aceitam controle apenas de programas do próprio computador (porta local), não de sites.
- Rodar os testes: `python -m unittest discover -s tests`.
