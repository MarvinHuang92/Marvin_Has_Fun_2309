0. 准备好所有要发送的附件文件或文件夹，放入 input 路径下
1. 运行 01_Package_Folder.bat，将 input 下的文件夹结构打包到 attachments 路径，并生成 dir_structure.txt 记录文件夹结构
2. 运行 02_Send_Mail.bat，依次输入如下参数：

- 收件人
- 附件所在的文件夹名（默认为 attachments，无需修改）
- 单个邮件支持的附件总大小（默认20MB）
- 两封邮件发送的时间间隔（默认10秒）
- 邮件发送方式（1.Outlook, 2.SMTP）
- 是否运行测试模式：输入Y将在本地生成邮件预览（message.html），输入N将正式发送邮件

脚本将创建一系列邮件，并尝试加入每一个附件（包含dir_structure.txt），当附件总尺寸超过限制时，会放入下一封邮件，直到全部附件发送完成

3. 在收件的电脑上，下载所有附件
将 dir_structure.txt 放入 attachments 路径下，其他所有附件放入 attachments/package 路径下
运行 03_Restore_Folder.bat，将 attachments 下的文件夹结构恢复，保存到 output 路径

==================================================

邮件内容示例：
Email 1 (3 attachments, 6MB in total)
- 附件1 (1MB)
- 附件2 (2MB)
- 附件3 (3MB)
Email 2 (3 attachments, 5MB in total) (This mail)
- 附件4 (1MB)
- 附件5 (2MB)
- dir_structure.txt (0MB)

当前邮件的内容将加粗显示，并在结尾显示 This mail

邮件全部列出后，显示总附件的【数量】和【大小】
Summary: 20 attachments available, 120 MB in total

如果有超出限制的单个文件，将在内容的结尾列出
Warning: Some Attachments are too large to be packed
- 附件7 (30MB)
- 附件8 (30MB)