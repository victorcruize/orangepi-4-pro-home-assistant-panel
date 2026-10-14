# Mídia do painel

Coloque aqui os dois arquivos usados pela abertura e pelo descanso de tela. Eles não fazem parte do
repositório, porque são a identidade visual de cada instalação.

| Arquivo | Uso | Recomendação |
|---|---|---|
| `logo.png` | descanso de tela: o logo pulsando sobre fundo escuro | PNG quadrado, com fundo transparente, 500 px ou mais |
| `logo-sketch.mp4` | abertura, tocada uma vez quando o painel inicia | vídeo quadrado de 3 a 5 segundos |

Depois rode, na pasta do painel:

```bash
python3 make_media.py
```

O script gera `intro.rgb565` e `saver.rgb565`, que são sequências de quadros de 480×320 já no formato do
visor. Precisa de `ffmpeg`, Pillow e NumPy.

Sem esses arquivos o painel funciona normalmente, apenas sem abertura e sem descanso de tela.
