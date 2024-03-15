from flask import Flask, render_template, request, Response, url_for, redirect
import requests
import time

AUTH_URL = "http://localhost:5000/v3"
NOVA_URL = "http://localhost:8774/v2.1"
NETWORK_URL = "http://localhost:9696/v2.0"
CINDER_URL = "http://localhost:8776/v3"
DOMAIN_NAME = "default"
SSH_KEY = "my_key"

app = Flask(__name__)

def authenticate(username, password, project):
    data = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": username,
                        "domain": {"name": DOMAIN_NAME },
                        "password": password
                    }
                }
            },
            "scope": {
                "project": {
                    "name": project,
                    "domain": {"name": DOMAIN_NAME }
                }
            }
        }
    }
    response = requests.post(AUTH_URL + "/auth/tokens", json=data)
    if response.status_code != 201:
        return None, None
    json_response = response.json()
    token = response.headers['X-Subject-Token']
    project_id = json_response['token']['project']['id']
    return token, project_id
def get_resources(AUTH_TOKEN, PROJECT_ID):
    response = requests.get(CINDER_URL + "/volumes", headers={"X-Auth-Token": AUTH_TOKEN})
    volumes = [[volume['name'], volume['id']] for volume in response.json()['volumes']]
    response = requests.get(NETWORK_URL + "/networks", headers={"X-Auth-Token": AUTH_TOKEN})
    networks = [[network['name'], network['id']] for network in response.json()['networks']]
    response = requests.get(NOVA_URL + "/flavors", headers={"X-Auth-Token": AUTH_TOKEN})
    flavors = [[flavor['name'], flavor['id']] for flavor in response.json()['flavors']]
    return volumes, networks, flavors
def create_volume(AUTH_TOKEN, PROJECT_ID, source, name):
    name = f"{name}_volume"
    data = {
        "volume": {
            "source_volid": source,
            "name": name
        }
    }
    response = requests.post(f"{CINDER_URL}/{PROJECT_ID}/volumes", headers={"X-Auth-Token": AUTH_TOKEN}, json=data)
    if response.status_code != 202:
        return None
    print(response.json())
    volume_id = response.json()['volume']['id']
    success = False
    for i in range(20):
        response = requests.get(f"{CINDER_URL}/{PROJECT_ID}/volumes/{volume_id}", headers={"X-Auth-Token": AUTH_TOKEN})
        if response.json()['volume']['status'] == "available":
            success = True
            break
        time.sleep(1)
    if success:
        return volume_id
    return None
def create_vm(AUTH_TOKEN,PROJECT_ID, name, volume, network, flavor):
    success = False
    # Создать копию диска
    volume_id = create_volume(AUTH_TOKEN, PROJECT_ID, volume, name)
    if volume_id is None:
        return success
    # Создать виртуальную машину
    flavor_url = f"{NOVA_URL}/flavors/{flavor}"
    data = {
        "server": {
            "name": name,
            "flavorRef": flavor_url,
            "key_name": SSH_KEY,
            "networks": [{"uuid": network}],
            "block_device_mapping_v2":
            [{
                "uuid": volume_id,
                "source_type": "volume",
                "destination_type": "volume",
                "boot_index": "0",
                "delete_on_termination": "true"
            }]
        }
    }
    response = requests.post(f"{NOVA_URL}/servers", headers={"X-Auth-Token": AUTH_TOKEN}, json=data)
    if response.status_code != 202:
        return success
    print(response.json())
    server_id = response.json()['server']['id']
    admin_pass = response.json()['server']['adminPass']
    volume = f"{name}_volume"
    # Дождаться пока машина запустится
    for i in range(20):
        response = requests.get(f"{NOVA_URL}/servers/{server_id}", headers={"X-Auth-Token": AUTH_TOKEN})
        if response.json()['server']['status'] == "ACTIVE":
            success = True
            break
        time.sleep(1)
    return server_id, admin_pass, volume, success


@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']
    project = request.form['project']
    AUTH_TOKEN, PROJECT_ID = authenticate(username, password, project)
    if AUTH_TOKEN is None or PROJECT_ID is None:
        return redirect(url_for("index"), code=302)
    resp = redirect(url_for("index"))
    resp.set_cookie('AUTH_TOKEN', AUTH_TOKEN)
    resp.set_cookie('PROJECT_ID', PROJECT_ID)
    return resp

@app.route('/', methods=['GET', 'POST'])
def index():
    AUTH_TOKEN = request.cookies.get('AUTH_TOKEN')
    PROJECT_ID = request.cookies.get('PROJECT_ID')
    if AUTH_TOKEN is None or PROJECT_ID is None:
        return render_template('login.html')
    if request.method == 'GET':
        volumes, networks, flavors = get_resources(AUTH_TOKEN, PROJECT_ID)
        page = render_template('index.html', volumes=volumes, networks=networks, flavors=flavors)
        resp = Response(page)
        resp.set_cookie('AUTH_TOKEN', AUTH_TOKEN)
        resp.set_cookie('PROJECT_ID', PROJECT_ID)
        return resp
    if request.method == 'POST':
        name = request.form['name']
        volume = request.form['volume']
        network = request.form['network']
        flavor = request.form['flavor']
        AUTH_TOKEN = request.cookies.get('AUTH_TOKEN')
        PROJECT_ID = request.cookies.get('PROJECT_ID')
        if name and volume and network and flavor:
            server_id, admin_pass, volume, success = create_vm(AUTH_TOKEN, PROJECT_ID, name, volume, network, flavor)
            if success:
                return render_template('vm.html', name=name, volume=volume, admin_pass=admin_pass)
            else:
                return "Error"
        else:
            return redirect(url_for("index"), code=302)

if __name__ == '__main__':
    app.run(debug=True, port=8000)