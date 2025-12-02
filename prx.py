# 2023122004 김동욱 Computer Network Proj. 3: HTTP Proxy Server
import socket
import sys
import threading

# 전역 변수: 요청 번호, 이미지 필터링 모드 (True면 이미지 차단)
REQUEST_COUNT = 0
IMAGE_FILTER_MODE = False 
# 락(Lock) 추가: 요청 번호를 안전하게 증가시키기 위해
count_lock = threading.Lock()
def handle_client(client_socket, client_addr):
    global IMAGE_FILTER_MODE, REQUEST_COUNT
    
    REDIRECTING = False
    
    # 이 스레드만의 로그 저장소
    FINAL_LOG = ""
    
    # 로그를 쌓는 내부 함수
    def print_queue(_msg, is_last=False, req_num=0, redirecting=False, image_filter=False):
        nonlocal FINAL_LOG
        if is_last:
            # 마지막에 헤더를 맨 앞에 붙여서 완성
            header = f"{req_num} [{'O' if redirecting else 'X'}] Redirected [{'O' if image_filter else 'X'}] Image filter"
            FINAL_LOG = header + "\n" + FINAL_LOG + _msg
        else:
            FINAL_LOG += _msg + "\n"

    try:
        # 1. 클라이언트 요청 수신
        request_data = client_socket.recv(4096)
        if not request_data:
            client_socket.close()
            return
        
        request_str = request_data.decode('utf-8', errors='ignore')
        
        # 요청 번호 할당
        with count_lock:
            REQUEST_COUNT += 1
            current_req_num = REQUEST_COUNT
            
        print_queue(f"[CLI connected to {client_addr[0]}:{client_addr[1]}]")
        
        # --- 파싱 로직 ---
        lines = request_str.split('\r\n')
        first_line = lines[0] # 예: GET http://mnet.yonsei.ac.kr/hw/sample3.html HTTP/1.1
        
        agent = "Unknown" # 예: User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ...
        for line in lines:
            if line.startswith("User-Agent:"):
                # 괄호 처리 등 단순화
                try:
                    agent = line.split(":", 1)[1].strip()
                except: pass
                break

        parts = first_line.split(' ')
        method = parts[0] # 예: GET
        full_url = parts[1] # 예: http://mnet.yonsei.ac.kr/hw/sample3.html
        version = parts[2] # 예: HTTP/1.1
        
        # http:// 제거한 전체 url
        # 예: mnet.yonsei.ac.kr/hw/sample3.html
        temp_url = full_url.replace("http://", "") if "http://" in full_url else full_url
        
        # 쿼리스트링 처리
        query_string = "" # 예: ?image_on
        if "?" in temp_url:
            parts_url = temp_url.split('?', 1)
            temp_url = parts_url[0]
            query_string = "?" + parts_url[1]
        
        # Host와 Path 분리
        # 예: mnet.yonsei.ac.kr/hw/sample3.html -> host: mnet.yonsei.ac.kr, path: /hw/sample3.html
        if "/" in temp_url:
            parts_host = temp_url.split('/', 1)
            target_host = parts_host[0]
            target_path = "/" + parts_host[1]
        else:
            target_host = temp_url
            if query_string:
                target_path = ""
            else:
                target_path = "/"

        # 포트 처리
        target_port = 80
        if ":" in target_host:
            target_host_only = target_host.split(':')[0]
            target_port = int(target_host.split(':')[1])
            target_host = target_host_only
        
        # Request Line 재조립
        lines[0] = f"{method} {target_path} {version}"

        # --- 헤더 수정 (Range 삭제 및 Keep-Alive 끄기) ---
        # 1바이트 요청 (206 Partial Content) 문제를 해결하기 위해 Range 헤더를 삭제
        lines_to_send = []
        for line in lines:
            line_lower = line.lower()
            if line_lower.startswith("connection:"): continue
            if line_lower.startswith("range:"): continue 
            lines_to_send.append(line)
        
        lines_to_send.insert(1, "Connection: close")
        modified_request_data = "\r\n".join(lines_to_send).encode('utf-8')
        
        # 로그: Request
        print_queue(f"[CLI ==> PRX --- SRV]\n\t > {method} {target_host}{target_path}{query_string}") 
        print_queue(f"> {agent}") 

        # 리다이렉션 체크
        # 예: google -> mnet.yonsei.ac.kr
        if "google" in target_host:
            target_host = "mnet.yonsei.ac.kr"
            REDIRECTING = True
        
        # 이미지 필터 모드 설정
        if "image_on" in query_string:
            IMAGE_FILTER_MODE = False
        elif "image_off" in query_string:
            IMAGE_FILTER_MODE = True
        
        # 2. 서버 연결
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.connect((target_host, target_port))
        
        print_queue(f"[SRV connected to {target_host}:{target_port}]")
        print_queue(f"[CLI --- PRX ==> SRV]\n\t > {method} {target_host}{target_path}") 
        print_queue(f"> {agent}") 

        # 요청 전송
        server_socket.send(modified_request_data) 
        
        # 3. 응답 처리 (Fetch-then-Block)
        first_response = True 
        image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.bmp', '.webp')
        
        # 미리 차단해야 할 요청인지 판단
        should_block = False
        if IMAGE_FILTER_MODE and target_path.lower().endswith(image_extensions):
            should_block = True

        while True:
            response_data = server_socket.recv(4096)
            
            if len(response_data) > 0:
                # 첫 패킷 처리
                if first_response:
                    try:
                        resp_str = response_data.decode('utf-8', errors='ignore')
                        resp_lines = resp_str.split('\r\n')
                        status_line = resp_lines[0].split(" ", 1)[1].strip()
                        
                        content_type = ""
                        content_length = len(response_data)
                        for line in resp_lines:
                            if line.lower().startswith("content-type:"):
                                content_type = line.split(":", 1)[1].strip()
                            elif line.lower().startswith("content-length:"):
                                content_length = line.split(":", 1)[1].strip()
                        
                        # [SRV -> PRX] 로그
                        print_queue(f"[CLI --- PRX <== SRV]")
                        print_queue(f" > {status_line}")
                        print_queue(f" > {content_type} {content_length}bytes")

                        if should_block:
                            # [차단 시] 404 전송 및 로그
                            not_found_msg = "HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\nContent-Length: 13\r\n\r\n404 Not Found"
                            client_socket.send(not_found_msg.encode('utf-8'))
                            
                            print_queue(f"[CLI <== PRX --- SRV]")
                            print_queue(f" > 404 Not Found")
                            break # 루프 종료 (더 이상 데이터 안 보냄)
                        else:
                            # [정상 시] 데이터 전달 및 로그
                            client_socket.send(response_data)
                            print_queue(f"[CLI <== PRX --- SRV]")
                            print_queue(f" > {status_line}")
                            print_queue(f" > {content_type} {content_length}bytes")
                            
                    except:
                        # 디코딩 에러 시 그냥 전송
                        if not should_block:
                            client_socket.send(response_data)

                    first_response = False
                
                else:
                    # 두 번째 패킷부터
                    if should_block:
                        break # 차단 모드면 더 이상 데이터 안 보냄 
                    else:
                        client_socket.send(response_data) # 정상 모드면 계속 전달
            else:
                break
        
        print_queue("[CLI disconnected]")
        print_queue("[SRV disconnected]")
        print_queue("--------------------------------", is_last=True, req_num=current_req_num, redirecting=REDIRECTING, image_filter=IMAGE_FILTER_MODE)
        print(FINAL_LOG)
        
        server_socket.close()
        client_socket.close()

    except Exception as e:
        # 에러 발생 시에도 로그 출력 시도
        if 'current_req_num' not in locals(): current_req_num = 0
        print_queue(f"Error: {e}", is_last=True, req_num=current_req_num, redirecting=REDIRECTING, image_filter=IMAGE_FILTER_MODE)
        print(FINAL_LOG)
        if client_socket: client_socket.close()

def main():
    if len(sys.argv) < 2:
        print("Usage: python prx.py <port>")
        sys.exit(1)

    port = int(sys.argv[1])
    
    proxy_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    proxy_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    proxy_server.bind(('', port))
    proxy_server.listen(10)
    
    print(f"Starting proxy server on port {port} \n --------------------------------")

    while True:
        try:
            # 클라이언트 연결 수락
            client_sock, client_addr = proxy_server.accept()
            
            # 쓰레드를 이용해 멀티 클라이언트 처리
            client_handler = threading.Thread(
                target=handle_client, 
                args=(client_sock, client_addr)
            )
            client_handler.daemon = True
            client_handler.start()
        except KeyboardInterrupt:
            print("\nShutting down proxy server.")
            proxy_server.close()
            sys.exit(0)

if __name__ == "__main__":
    main()