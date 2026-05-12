# Ollama API Python 程式建立紀錄

## 目標

建立一支可串接本機 Ollama API 的 Python 程式 `ollama-api.py`，並使用設定檔中的參數送出問題。

本次設定檔內容為：

```txt
question="Hello"
```

## 建立過程

1. 確認工作目錄為 `OllamaApi`，且現有設定檔為 `config-ollama-api.txt`。
2. 讀取設定檔內容，確認目前至少包含 `question="Hello"`。
3. 新增 `OllamaApi/ollama-api.py`，功能包含：
   - 自動尋找 `config-ollama-api.txt`
   - 相容讀取使用者需求中提到的 `config-ollama-apy.txt` 拼字
   - 解析 `key=value` 格式設定
   - 以 HTTP POST 呼叫本機 Ollama API
   - 預設使用 `http://localhost:11434/api/generate`
   - 若未指定 `model`，自動偵測本機已安裝的第一個模型
4. 針對新建立的 Python 檔執行語法驗證，確認可通過編譯檢查。
5. 直接執行腳本，確認在目前環境中可成功送出 `question="Hello"`。
6. 新增回應輸出功能，將 API 回傳內容寫入 `OllamaApi/output.txt`。

## 設定檔格式

目前最小可用設定如下：

```txt
question="Hello"
```

也可以擴充為：

```txt
question="Hello"
base_url="http://localhost:11434"
endpoint="/api/generate"
stream="false"
timeout="60"
system="You are a helpful assistant."
```

## 執行方式

在專案根目錄執行：

```powershell
C:/Users/User/AppData/Local/Programs/Python/Python39/python.exe OllamaApi/ollama-api.py
```

執行完成後，回應內容會寫入 `OllamaApi/output.txt`。

## 程式行為

- 若設定檔只有 `question="Hello"`，程式會使用預設本機位址，並自動選擇第一個已安裝模型送出請求。
- API 成功回傳後，程式會將回應文字輸出到 `OllamaApi/output.txt`。
- 若本機 Ollama 未啟動，程式會回報連線錯誤。
- 若模型名稱不存在，Ollama 會回傳 API 錯誤訊息。

## 驗證結果

已完成 Python 語法檢查：

- `python -m py_compile OllamaApi/ollama-api.py`

語法檢查通過。

已完成實際 API 呼叫驗證：

- 讀取 `config-ollama-api.txt`
- 送出問題 `Hello`
- 成功取得回應 `Hello! How can I help you today?`
- 回應同步寫入 `OllamaApi/output.txt`