# -*- coding: utf-8 -*-

# 使用python调用outlook发送邮件，参考: https://www.jianshu.com/p/4f0ed762f521
# 使用python调用STMP发送邮件，参考: https://www.runoob.com/python/python-email.html

import os
import sys
import shutil
import win32com.client as win32  # pip install pywin32
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

class MailInfo:
    def __init__(self, title, recipients, cc, html_msg, attachments=None):
        self.title = title
        self.recipients = recipients
        self.cc = cc
        self.html_msg = html_msg
        self.attachments = attachments
    
    def get_abs_attachment_paths(self, attachment_dir):
        abs_paths = []
        for attachment in self.attachments:
            abs_path = os.path.abspath(os.path.join(attachment_dir, attachment))
            abs_paths.append(abs_path)
        return abs_paths


class AttachmentPackInfo:
    def __init__(self, attachment_files, attachment_sizes):
        self.attachment_files = attachment_files
        self.attachment_sizes = attachment_sizes


# To pack files in the directory into multiple packages, each not exceeding size_limit_mb
def pack_attachments(attachment_dir, size_limit_mb):
    packages_valid = []
    packages_invalid = []
    current_package = AttachmentPackInfo([], [])
    current_package_size = 0.0
    safe_margin = 0.98

    # get all attachment files with their sizes in MB
    all_attachment_files = os.listdir(attachment_dir)
    all_attachment_sizes = [os.path.getsize(os.path.join(attachment_dir, f)) / (1024 * 1024) for f in all_attachment_files]
    print("") # blank line
    for i in range(len(all_attachment_files)):
        print('Found attachment: %s (%.2f MB)' % (all_attachment_files[i], all_attachment_sizes[i]))
        if all_attachment_sizes[i] > size_limit_mb * safe_margin:
            # file too large, cannot be packed
            print('  -> Attachment too large (%.2f MB), cannot be packed into email with size limit of %d MB' % (all_attachment_sizes[i], size_limit_mb))
            packages_invalid.append(AttachmentPackInfo([all_attachment_files[i]], [all_attachment_sizes[i]]))
            continue
        if current_package_size + all_attachment_sizes[i] <= size_limit_mb * safe_margin:
            # add to current package
            current_package.attachment_files.append(all_attachment_files[i])
            current_package.attachment_sizes.append(all_attachment_sizes[i])
            current_package_size += all_attachment_sizes[i]
        else:
            # save current package
            packages_valid.append(current_package)
            # start a new package
            current_package = AttachmentPackInfo([all_attachment_files[i]], [all_attachment_sizes[i]])
            current_package_size = all_attachment_sizes[i]

    # Append the last package if it has any files
    if current_package.attachment_files:
        packages_valid.append(current_package)

    return packages_valid, packages_invalid


def send_mail_via_Outlook(mail_info, attachment_dir='.'):
    outlook = win32.Dispatch('Outlook.Application')

    mail = outlook.CreateItem(0) # 0: olMailItem
    
    mail_to_str = ''
    for recipient in mail_info.recipients:
        mail_to_str += (recipient + ';')
        # This is another way rather than using "mail.To"
        # mail.Recipients.Add(recipient)
    
    mail_cc_str = ''
    for cc_name in mail_info.cc:
        mail_cc_str += (cc_name + ';')
        
    mail.To = mail_to_str
    mail.CC = mail_cc_str
    
    mail.Subject = mail_info.title

    mail.BodyFormat = 2  # 2: Html format
    mail.HTMLBody = mail_info.html_msg

    if mail_info.attachments:
        for attachment_abs_path in mail_info.get_abs_attachment_paths(attachment_dir):
            print('Attaching file: ' + attachment_abs_path)
            mail.Attachments.Add(attachment_abs_path)

    mail.Send()

def send_mail_via_SMTP(mail_info, attachment_dir='.'):
    # QQ邮箱 IMAP/SMTP 设置方法
    # 用户名/帐户： 你的QQ邮箱完整的地址
    # 密码： 生成的授权码
    # 电子邮件地址： 你的QQ邮箱的完整邮件地址
    # 接收邮件服务器： imap.qq.com，使用SSL，端口号993
    # 发送邮件服务器： smtp.qq.com，使用SSL，端口号465或587

    # 发件人和收件人信息
    mail_host = "smtp.qq.com"
    sender_email = "marvinhuang@qq.com"
    sender_password = "yovcwqbxjbyobfcb"  # POP3/IMAP/SMTP授权码，而不是密码

    receiver_email = ''
    for recipient in mail_info.recipients:
        receiver_email += (recipient + ';')
    receiver_email = receiver_email.strip(";")

    # 创建邮件
    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = receiver_email
    message["Subject"] = mail_info.title

    # 添加邮件正文
    # message.attach(MIMEText("邮件正文", "plain"))  # 普通文字格式
    message.attach(MIMEText(html_msg, 'html', 'utf-8'))  # HTML格式

    # 添加附件
    if mail_info.attachments:
        for attachment_abs_path in mail_info.get_abs_attachment_paths(attachment_dir):
            print('Attaching file: ' + attachment_abs_path)
            with open(attachment_abs_path, "rb") as attachment:
                part = MIMEApplication(attachment.read(), Name=attachment_abs_path)
                part["Content-Disposition"] = 'attachment; filename="%s"' % attachment_abs_path
                message.attach(part)

    # 发送邮件
    try:
        # 连接到SMTP服务器
        smtpObj = smtplib.SMTP_SSL(mail_host, 465)
        # smtpObj.starttls()  # 有的邮箱不支持TLS，注释掉即可
        smtpObj.login(sender_email, sender_password)
        smtpObj.sendmail(sender_email, receiver_email, message.as_string())
        smtpObj.quit()
        print("邮件发送成功！")
    except smtplib.SMTPException as e:
        print(f"邮件发送失败: {e}")


if __name__ == '__main__':
    
    # Get inputs from command line arguments
    if len(sys.argv) != 7:
        print('Usage: python send_email_with_auto_packed_attachments.py <recipient_email> <attachment_directory> <attachment_size_limit_MB> <interval_seconds> <sending_app> <test_mode_Y/N>')
        sys.exit(1)
    recipient = str(sys.argv[1]).strip()
    attachment_dir = str(sys.argv[2]).strip()
    attachment_size_limit = int(sys.argv[3])
    interval = int(sys.argv[4])
    sending_app = str(sys.argv[5])
    test_mode = str(sys.argv[6]).strip()  # Y = generate message only, N = send email

    # Generate Message or Send Email?
    send_mail_switch = test_mode == "N" or test_mode == "n"

    # check if package folder exists
    package_dir_exist = os.path.isdir(os.path.join(attachment_dir, "package"))
    dir_structure_file_exist = os.path.isfile(os.path.join(attachment_dir, "dir_structure.txt"))
    print("") # blank line
    print('Scanning attachments: package folder existance: %s' % str(package_dir_exist))
    print('Scanning attachments: dir_structure.txt existance: %s' % str(dir_structure_file_exist))
    
    if package_dir_exist:
        # set package folder as attachment_dir
        attachment_dir = os.path.join(attachment_dir, "package")
        # copy dir_structure.txt into package folder
        if dir_structure_file_exist:
            shutil.copy(os.path.join(attachment_dir, "../dir_structure.txt"), attachment_dir)

    # Get all attachment files with their sizes in MB
    packages_valid, packages_invalid = pack_attachments(attachment_dir, attachment_size_limit)
    packages_valid_count = len(packages_valid)
    
    # Prepare valid package info for HTML message
    html_package_summary_list = []
    html_package_info_list = []
    attachment_count_valid = 0
    total_size_valid = 0.0
    for i in range(packages_valid_count):
        attachments = packages_valid[i].attachment_files
        sizes = packages_valid[i].attachment_sizes
        
        html_package_summary_list.append('<b>Email %d (%d attachments, %.2f MB in total)</b>' % (i + 1, len(attachments), sum(sizes)))
        html_package_info = ""
        for j in range(len(attachments)):
            html_package_info += '- %s (%.2f MB)<br>' % (attachments[j], sizes[j])
        html_package_info_list.append(html_package_info)
        
        attachment_count_valid += len(attachments)
        total_size_valid += sum(sizes)
    
    # Prepare invalid package info for HTML message
    html_invalid_package_summary = ""
    html_invalid_package_info = ""
    total_size_invalid = 0.0
    for i in range(len(packages_invalid)):
        html_invalid_package_info += '<br>- %s (%.2f MB)' % (packages_invalid[i].attachment_files[0], packages_invalid[i].attachment_sizes[0])
        total_size_invalid += packages_invalid[i].attachment_sizes[0]
    if len(packages_invalid) > 0:
        html_invalid_package_summary = '<br><b style="color: red;">Warning: Some Attachments are too large to be packed</b><br>'
        html_invalid_package_summary += html_invalid_package_info + '<br><br>'
        html_invalid_package_summary += '<b>Summary: %d attachments unavailable, %.2f MB in total</b><br><br>' % (len(packages_invalid), total_size_invalid)
        html_invalid_package_summary += "<b>============================================</b><br>"

    # Email Content Parameters
    recipients = [recipient,]  # Add more recipients if needed
    cc = []  # Add CC recipients if needed
    first_attachment = packages_valid[0].attachment_files[0] if packages_valid else "No Attachments"

    print("") # blank line
    for i in range(packages_valid_count):
        print('[Info] Attachment package %d:\n- %s\n(Total size: %.2f MB)' % (i + 1, "\n- ".join(packages_valid[i].attachment_files), sum(packages_valid[i].attachment_sizes)))
        attachments = packages_valid[i].attachment_files
        mail_title = '[%d/%d] %s' % (i + 1, packages_valid_count, first_attachment)
        html_attachments_info = "<b>=========== Available attachments ===========</b><br><br>"
        for j in range(0, i):
            html_attachments_info += html_package_summary_list[j] + '<br>' + html_package_info_list[j] + '<br>'
        # when j == i:
        html_attachments_info += html_package_summary_list[i] + '<b style="color: blue;">(This mail)</b><br>' + html_package_info_list[i] + '<br>'
        for j in range(i + 1, packages_valid_count):
            html_attachments_info += html_package_summary_list[j] + '<br>' + html_package_info_list[j] + '<br>'

        html_attachments_info += "<b>Summary: %d attachments available, %.2f MB in total</b><br><br>" % (attachment_count_valid, total_size_valid)
        html_attachments_info += "<b>============================================</b><br>"
    
        # Get current date and time
        datetime_str = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # HTML Message
        # 注意其中所有的 http link 都要单独作为一个 %s 传入，而不能在 HTML 内部拼接，否则报错
        html_msg = """
        <html>

        <p style="font-family:Arial;font-size:14px;">
        <br>This is the <b>%d/%d</b> email to notify you that the auto-packed attachments are ready to use.
        <br>
        <br>All attachments are packed with size limit of <b>%d MB</b> per email.
        </p>

        <p style="font-family:Courier New;font-size:12px;">
        <br>%s
        <br>%s
        <br>
        </p>

        <p style="font-family:Arial;font-size:14px;">
        <br>%s
        </p>

        </html>
        """ % (i + 1, packages_valid_count, attachment_size_limit, html_attachments_info, html_invalid_package_summary, datetime_str)


        # Send Email or Generate Message
        if send_mail_switch:
            print('Sending Email... [%d/%d]' % (i + 1, packages_valid_count))
            print("") # blank line
            print('Title: ' + mail_title)
            print('TO: ' + str(recipients))
            print('CC: ' + str(cc))
            mail_info = MailInfo(mail_title, recipients, cc, html_msg, attachments)
            if sending_app == "outlook":
                send_mail_via_Outlook(mail_info, attachment_dir)
            else:  # sending_app == "smtp"
                send_mail_via_SMTP(mail_info, attachment_dir)
        else:
            print('Generating Email Message... [%d/%d]' % (i + 1, packages_valid_count))
            print("") # blank line
            with open('message_%d_of_%d.html' % (i + 1, packages_valid_count), 'w') as f:
                f.write('<h2>\nTitle: ' + mail_title + '\n</h2>')
                f.write('<br>TO: ' + str(recipients))
                f.write('<br>CC: ' + str(cc))
                f.write(html_msg)
                f.close()
        # Wait for the specified interval before sending the next email
        if i < packages_valid_count - 1:
            print('Waiting for %d seconds before sending the next email...' % interval)
            print("") # blank line
            __import__('time').sleep(interval)

    for i in range(len(packages_invalid)):
        print('[Warning] Attachment too large to be packed: %s (%.2f MB)' % (packages_invalid[i].attachment_files[0], packages_invalid[i].attachment_sizes[0]))

    if package_dir_exist and dir_structure_file_exist:
        # remove dir_structure.txt in package folder
        os.remove(os.path.join(attachment_dir, "dir_structure.txt"))

    # End of script