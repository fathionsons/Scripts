import os
import shutil
import stat
import ctypes
import sys

def is_admin():
    """Check if the script is running as an administrator."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def delete_temp_files():
    temp_dir = os.getenv('TEMP')  # Path to the temp folder
    print(f"Temp directory being cleaned: {temp_dir}")
    if temp_dir and os.path.exists(temp_dir):
        print(f"Deleting files in: {temp_dir}")
        for item in os.listdir(temp_dir):
            item_path = os.path.join(temp_dir, item)
            try:
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.unlink(item_path)  # Remove file or link
                    print(f"Deleted file: {item_path}")
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path, ignore_errors=True)  # Remove directory
                    print(f"Deleted directory: {item_path}")
            except PermissionError:
                print(f"Permission Denied: {item_path}. Attempting force delete...")
                force_delete(item_path)  # Attempt force deletion
            except OSError as e:
                print(f"Error deleting {item_path}: {e}")
    else:
        print("Temp folder not found or inaccessible!")

def delete_prefetch_files():
    prefetch_dir = r"C:\Windows\Prefetch"  # Path to the prefetch folder
    if os.path.exists(prefetch_dir):
        print(f"Deleting files in: {prefetch_dir}")
        for item in os.listdir(prefetch_dir):
            item_path = os.path.join(prefetch_dir, item)
            try:
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.unlink(item_path)
                    print(f"Deleted file: {item_path}")
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path, ignore_errors=True)
                    print(f"Deleted directory: {item_path}")
            except PermissionError:
                print(f"Permission Denied: {item_path}. Attempting force delete...")
                force_delete(item_path)  # Attempt force deletion
            except OSError as e:
                print(f"Error deleting {item_path}: {e}")
    else:
        print("Prefetch folder not found or inaccessible!")

def force_delete(file_path):
    """Attempt to forcefully delete a file or directory."""
    try:
        if os.path.isfile(file_path) or os.path.islink(file_path):
            os.chmod(file_path, stat.S_IWRITE)  # Change file to writable
            os.unlink(file_path)
            print(f"Force deleted file: {file_path}")
        elif os.path.isdir(file_path):
            # Remove hidden and system attributes from the directory
            ctypes.windll.kernel32.SetFileAttributesW(file_path, 0x80)  # FILE_ATTRIBUTE_NORMAL
            shutil.rmtree(file_path, ignore_errors=True)
            print(f"Force deleted directory: {file_path}")
    except Exception as e:
        print(f"Unable to force delete {file_path}: {e}")

if __name__ == "__main__":
    # Check for admin privileges
    if not is_admin():
        print("Requesting administrator privileges...")
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, __file__, None, 1)
        sys.exit()

    print("Starting cleanup...")
    delete_temp_files()
    delete_prefetch_files()
    print("Cleanup complete!")