# 3 秒图生视频参考帧包

这些是供外部 image-to-video 工具使用的**参考静帧**，不是已生成的视频：

- `00_start.jpg` — 起始状态（0.0s）：对峙，女主伞盾已举起，男主剑指向盾。
- `01_clash.jpg` — 中间动作锚点（约 1.5s）：男主前冲，剑击中伞盾。
- `02_end.jpg` — 结束状态（约 3.0s）：冲击后男主退半步、伞盾仍稳住，火花收束。
- `contact_sheet.jpg` — 三帧并排预览。

## 可直接复制的视频提示词

先在视频工具中上传 `00_start.jpg` 作为首帧、`02_end.jpg` 作为尾帧；如果支持额外参考图，再上传 `01_clash.jpg` 作为中间动作锚点。随后粘贴：

> 生成一段 3 秒、16:9 的电影感连续动作镜头。严格以首帧和尾帧作为画面起止状态；中间参考图只用于约束交锋动作。固定中景广角镜头，机位稳定，不切镜、不变焦。场景始终是雨中的圆形石台与青色风暴遗迹。
>
> 动作按时间推进：0–0.5 秒，两人短暂对峙蓄势；0.5–1.4 秒，白衣黑发男剑客向右前方快速踏步刺出；1.4–1.8 秒，剑尖撞上银发女剑客的圆形伞盾，接触点迸出一簇短促、局部的金青火花；1.8–2.4 秒，男剑客受力后撤半步、剑锋下沉，女剑客稳稳持盾；2.4–3.0 秒，两人停在尾帧姿势，火花熄弱，雨势持续。动作有明确的起势、加速、碰撞和回稳，人物身体与武器做连贯的真实运动，不做静帧推拉。
>
> 全程保持两位角色与参考图一致：同一张脸、发型、年龄感、身形、服装颜色与结构；男角色只持一把直剑，女角色只持一面圆形伞盾。白衣袖口、衣摆长度和分片保持稳定，不凭空增加长尾或飘带。伞盾结构不变。背景石柱、圆形石台及远处建筑位置稳定；只允许人物、武器、接触火花和少量近身雨水运动。脸部清晰可辨，人体关节自然，动作流畅有重量感，电影级写实奇幻质感。

**负面提示词**（若工具有单独栏位）：

> face morphing, identity change, costume change, extra limbs, duplicate person, duplicate sword, duplicate shield, extra weapon, long trailing cloth, extra ribbons, melting body, warped anatomy, flickering, full-frame ripple, background bending, camera shake, zoom, cuts, giant explosion, excessive sparks, text, logo, subtitles

**注意**：这些关键帧只提供首/中/尾构图与动作约束，不能单独保证视频模型的时序一致性；生成后仍须逐帧检查脸、衣物轮廓和接触动作。

## 优化版提示词（下一轮生成用，v2）

这是针对首版“前段停顿偏长、盾方受力反应弱、碰撞光效偏强”的改进提示词；**尚未用于重新生成**。保持首帧/尾帧双锚：`00_start.jpg` 作首帧，`02_end.jpg` 作尾帧。当前视频模型若强制生成 4 秒，请把完整动作安排在前 3 秒，3–4 秒保持结束姿势与环境雨势，之后裁取前 3 秒。

> 生成 16:9、24fps、单镜头电影感动作视频。严格匹配首帧中的两位角色、服装、武器、构图与石台场景，并在动作结束时回到尾帧指定姿势。镜头固定，不切镜、不变焦、不做数字推拉；背景建筑、石柱和圆形石台保持稳定。
>
> 动作必须从开场很快开始，避免长时间静止：0–0.2 秒仅短暂对峙；0.2–0.85 秒，白衣黑发男剑客以清楚的脚步蹬地、重心前移，向右前方连续突进并刺剑，身体和剑产生真实位移；银发女剑客同步追踪来剑，移动伞盾迎击并稳住下盘。0.85–1.25 秒，剑与盾清晰接触，盾面只向后偏转少许，女剑客肩部和躯干出现短促受力回弹、脚步微调后立稳；接触点出现短暂、局部、克制的金色火花。1.25–2.2 秒，男剑客受力后撤半步，剑锋顺势下沉，身体重心重新落稳；女剑客恢复防守姿态。2.2–3.0 秒，动作收住并稳定在尾帧姿势，火花熄灭，只有雨水和少量衣料余摆继续运动。整套动作一气呵成，人物通过脚步、重心、关节和武器惯性完成真实攻防，不瞬移、不像静帧幻灯片。
>
> 保持人物身份、脸型、发型、年龄感和身形稳定：男剑客始终是黑色高束发、白色短结构汉服与深色腰带，只持一把直剑；女剑客始终是银色长发、深青黑色金纹护甲，只持同一把圆形伞盾。衣服跟随身体惯性自然摆动，但衣摆长度和分片不变，不生成长尾、飘带或额外布料。伞盾保持完整圆形与原有纹样，不融化、不变形。脸部尽量清晰，四肢和手指结构正确。碰撞光效小而有力，不遮住人物、剑和盾。

**负面提示词**（若工具提供单独栏位）：

> long static hold, slideshow, pose morphing, teleporting, face drift, identity change, costume change, extra limbs, duplicate person, duplicate sword, duplicate shield, extra weapon, long trailing cloth, extra ribbons, melting body, warped anatomy, shield deformation, full-frame ripple, background bending, camera shake, zoom, cuts, giant flash, giant explosion, overexposed contact, sparks covering faces, text, logo, subtitles
