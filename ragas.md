# RAGAS 評估程式建置紀錄

## 目標

建立一支可讀取 [Ragas/config-ragas.txt](Ragas/config-ragas.txt) 的 Python 程式 [Ragas/ragas.py](Ragas/ragas.py)，使用 RAGAS 評估 [ApikeyHidding/apikeyhidding.py](ApikeyHidding/apikeyhidding.py) 產生的 [ApikeyHidding/output.txt](ApikeyHidding/output.txt) 對話品質，並將評分結果輸出到 [Ragas/output.txt](Ragas/output.txt)。

## 建立過程

1. 檢查 [ApikeyHidding/apikeyhidding.py](ApikeyHidding/apikeyhidding.py) 與 [ApikeyHidding/config-apikeyhidding.txt](ApikeyHidding/config-apikeyhidding.txt)，確認可直接取得原始問題 `request` 與對話回覆檔 [ApikeyHidding/output.txt](ApikeyHidding/output.txt)。
2. 檢查 [Ragas/config-ragas.txt](Ragas/config-ragas.txt) 現況，確認需要補齊評估模型、來源檔案與輸出檔案等設定。
3. 新增 [Ragas/ragas.py](Ragas/ragas.py)，實作以下流程：
   - 讀取 `config-ragas.txt`
   - 載入 `ApikeyHidding/config-apikeyhidding.txt` 內的 `request` 作為使用者輸入
   - 載入 `ApikeyHidding/output.txt` 作為模型回答
   - 使用 RAGAS 建立 single-turn evaluation dataset
   - 以 `ResponseRelevancy` 與 `AspectCritic` 評估回答品質
   - 將各項分數與整體平均分數寫入 [Ragas/output.txt](Ragas/output.txt)
4. 補齊 [Ragas/config-ragas.txt](Ragas/config-ragas.txt) 預設參數，讓程式可直接評估目前的 Hello 對話結果。
5. 安裝 `ragas` 與 `langchain-ollama` 等相依套件，並在虛擬環境中驗證程式可以執行。
6. 執行過程中發現 [Ragas/ragas.py](Ragas/ragas.py) 檔名會遮蔽外部 `ragas` 套件，因此調整匯入方式，改為顯式載入已安裝套件。
7. 針對本機 Ollama 評估超時與輸出格式解析失敗問題，將 RAGAS 執行改為 `max_workers=1`、限制 `num_predict=128`，並強制評估模型使用 JSON 輸出模式。

## 參數檔格式

目前可用設定如下：

```txt
target_config=../ApikeyHidding/config-apikeyhidding.txt
target_output=../ApikeyHidding/output.txt
base_url=http://localhost:11434
model=qwen3.5:4b
embedding_model=nomic-embed-text
output=./output.txt
timeout=600
max_workers=1
num_predict=128
```

說明：

- `target_config` 指向被評估對話的設定檔，預設讀取其中的 `request` 當作 `user_input`。
- `target_output` 指向被評估對話的回答檔。
- `output` 為 RAGAS 評估結果輸出位置。
- `max_workers=1` 可避免本機 Ollama 同時處理多個評估請求時超時。
- `num_predict=128` 用來限制評估模型輸出長度，縮短評估時間。

## 執行方式

在專案根目錄執行：

```powershell
d:/Code/CodingP/05P-SinoClass/.venv/Scripts/python.exe Ragas/ragas.py
```

## 預期行為

- 程式會讀取 [Ragas/config-ragas.txt](Ragas/config-ragas.txt) 的評估設定。
- 程式會自動抓取 [ApikeyHidding/config-apikeyhidding.txt](ApikeyHidding/config-apikeyhidding.txt) 中的原始問題與 [ApikeyHidding/output.txt](ApikeyHidding/output.txt) 中的回答。
- 程式會使用 RAGAS 對單輪對話做評分，輸出各指標與整體分數到 [Ragas/output.txt](Ragas/output.txt)。

## 驗證結果

- 已執行 `python -m py_compile Ragas/ragas.py`
- 已安裝 `ragas`、`langchain-ollama`、`datasets`
- 已執行 `python Ragas/ragas.py`
- 成功讀取 [ApikeyHidding/config-apikeyhidding.txt](ApikeyHidding/config-apikeyhidding.txt) 與 [ApikeyHidding/output.txt](ApikeyHidding/output.txt)
- 成功以 `qwen3.5:4b` 與 `nomic-embed-text` 完成單輪對話評估
- 已輸出評估結果到 [Ragas/output.txt](Ragas/output.txt)
- 本次 `Hello` 對話的 `answer_relevancy` 為 `0.6639`
- 本次 `Hello` 對話的 `conversation_quality` 為 `1`
- 本次整體分數為 `0.8320`