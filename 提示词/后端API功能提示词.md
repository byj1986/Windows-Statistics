# 后端API功能提示词

- 在同一个python程序中，提供后端API
  - 启动后，启动一个http服务端口号为8000
    - '/api/dates/'
      获取当前目录的日期列表，由于日期分散于各个YYYYMM文件夹，需要遍历各文件夹
    - '/api/data/YYYYMMDD'
      YYYYMMDD由请求传入所需日期，如果日期不存在则返回{"sessions": [], "idle":0, "apps": {}}
