# 自托管工作台字体来源

字体来自固定供体提交`45a5921011fa22f400482f73710e96a32b916082`的`frontend/package-lock.json`，采用已安装的`@fontsource-variable/inter@5.3.0`及`@fontsource-variable/noto-sans-sc@5.3.0`。没有安装新包或联网取字体。两个本机既有npm缓存tarball的SHA512均匹配供体lock中的integrity；复制的CSS、许可、元数据与每个woff2也逐字匹配这些已核tarball。[精确来源](sources.json)登记完整integrity、锁SHA及原index.css SHA。

## 资产及覆盖

| 字体族 | 资产 | 范围 |
| --- | --- | --- |
| `Inter Variable` | 7个woff2，218512字节 | 上游index.css全部normal字形、100—900可变字重 |
| `Noto Sans SC Variable` | 101个woff2，4516508字节 | 上游index.css全部Unicode-range，含完整发布的简体中文分片及拉丁/其他配套分片，100—900可变字重 |

不按页面或截图抽取文字子集，也不重新生成或修改字体文件；保留上游完整normal覆盖和原`unicode.json`。这不是全Unicode字库承诺；原包未覆盖的字符仍需系统fallback。上游未在index.css导入的Inter独立italic/opsz变体不属于本次normal字体切片。

应用`src/fusion-fonts.css`保留全部108个原`@font-face`、原Unicode-range、字重和`font-display:swap`，只将字体URL改为本站绝对路径`/fonts/fusion/...`并作代码格式化；没有第三方字体请求、远程`@import`或字体预加载。浏览器按实际字符范围请求对应分片，未强制一次下载全部CJK字库。最终字体栈和浏览器字体验证由主样式接入；不表示整套字号、密度、缩放及所有业务页面已验收。

## 许可与完整性

两字体均采用SIL Open Font License 1.1，保留原版权和完整许可：

- [Inter LICENSE](inter/LICENSE)
- [Noto Sans SC LICENSE](noto-sans-sc/LICENSE)

各目录的`index.css`、`metadata.json`、`unicode.json`、`package.json`为原字节来源记录，供独立核对；应用只引用`src/fusion-fonts.css`。这批公开字体资产不含业务原件。所有分发资产及来源文件的大小/SHA见[manifest](manifest.json)；目录级`-text`保护原字节不受Git换行转换。应用CSS最终SHA在manifest的`application_css`字段登记，格式化后重核。
